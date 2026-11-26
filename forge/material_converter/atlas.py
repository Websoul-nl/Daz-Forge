"""Reproject color and data maps using a region-aware G9 UV transfer."""

from functools import lru_cache
from pathlib import Path

import numpy as np
from PySide6.QtGui import QColorSpace, QImage, QImageReader, QImageWriter

from .uv_lookup import decode_uv_lookup


@lru_cache(maxsize=2)
def read_pixels(path: Path, color: bool) -> np.ndarray:
    reader = QImageReader(str(path))
    img = reader.read()
    if img.isNull():
        raise ValueError(f"Cannot read {path.name}: {reader.errorString()}")
    srgb = QColorSpace(QColorSpace.NamedColorSpace.SRgb)
    if color and img.colorSpace().isValid() and img.colorSpace() != srgb:
        img = img.convertedToColorSpace(srgb)
    img = img.convertToFormat(QImage.Format.Format_RGBA64)
    pixels = np.frombuffer(img.constBits(), dtype=np.uint16).reshape(img.height(), -1)
    rgba = pixels[::-1, :img.width()*4].reshape(img.height(), img.width(), 4).astype(np.float32) / 65535
    if color:
        rgb = rgba[..., :3]
        rgb[:] = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4) * rgba[..., 3:4]
    return rgba


def write_pixels(path: Path, pixels: np.ndarray, color: bool) -> None:
    data = pixels.copy()
    if color:
        alpha = data[..., 3:4]
        rgb = np.divide(data[..., :3], alpha, out=np.zeros_like(data[..., :3]), where=alpha > 1e-8)
        data[..., :3] = np.where(rgb <= .0031308, rgb * 12.92, 1.055 * np.maximum(rgb, 0) ** (1 / 2.4) - .055)
    if not np.isfinite(data).all():
        raise ValueError("Texture contains nonfinite pixels")
    data = np.ascontiguousarray(np.rint(np.clip(data[::-1], 0, 1) * 65535).astype(np.uint16))
    img = QImage(data.data, data.shape[1], data.shape[0], data.strides[0], QImage.Format.Format_RGBA64)
    if color:
        img.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    writer = QImageWriter(str(path), b"png")
    writer.setCompression(10)
    if not writer.write(img):
        raise OSError(f"{path.name}: {writer.errorString()}")


def read_transfer(path: Path, *, labels: str = "source_id") -> tuple[np.ndarray, np.ndarray]:
    with np.load(path, allow_pickle=False) as cache:
        uv, ids = decode_uv_lookup(cache["uv"]), cache[labels]
    if ids.shape != uv.shape[:2] or ids.dtype.kind not in "ui" or np.any(ids < 0):
        raise ValueError(f"Invalid surface IDs in {path.name}")
    return uv, ids


def texel_centers(source: int, target: int) -> np.ndarray:
    """Target pixel centers expressed in the source grid's pixel coordinates."""
    centers = (np.arange(target, dtype=np.float64) + .5) * (source / target) - .5
    return np.clip(centers, 0, source - 1)


class TransferGrid:
    """Evaluate the lookup on a different pixel grid, not a resampled texture."""

    def __init__(self, uv: np.ndarray, ids: np.ndarray):
        self.uv, self.ids = uv, ids
        self._resized = None

    def at_size(self, size: int) -> tuple[np.ndarray, np.ndarray]:
        h, w = self.ids.shape
        if (h, w) == (size, size):
            return self.uv, self.ids
        if self._resized is not None and self._resized[1].shape == (size, size):
            return self._resized

        cx, cy = texel_centers(w, size), texel_centers(h, size)
        x0, y0 = cx.astype(np.intp), cy.astype(np.intp)
        x1, y1 = np.minimum(x0 + 1, w - 1), np.minimum(y0 + 1, h - 1)
        xn, yn = (cx + .5).astype(np.intp), (cy + .5).astype(np.intp)
        wx, wy = (cx - x0).astype(np.float32), (cy - y0).astype(np.float32)
        out = np.empty((size, size, 2), dtype=self.uv.dtype)
        labels = self.ids[yn[:, None], xn]
        # A donor ID can contain several disconnected UV islands.
        max_uv_step = 4 / min(h, w)
        for start in range(0, size, 64):
            row = slice(start, start + 64)
            nearest = self.uv[yn[row, None], xn]
            local = labels[row]
            smooth = local != 0
            coords = np.zeros_like(nearest)
            for yi, dy in ((y0, 1-wy), (y1, wy)):
                for xi, dx in ((x0, 1-wx), (x1, wx)):
                    points = self.uv[yi[row, None], xi]
                    weight = dy[row, None] * dx
                    same = (self.ids[yi[row, None], xi] == local) & (
                        np.max(np.abs(points - nearest), axis=-1) <= max_uv_step
                    )
                    smooth &= (weight == 0) | same
                    coords += points * weight[..., None]
            out[row] = np.where(smooth[..., None], coords, nearest)
        self._resized = out, labels
        return self._resized


def sample(pixels: np.ndarray, uv: np.ndarray) -> np.ndarray:
    h, w = pixels.shape[:2]
    xy = np.clip(uv * np.array([w, h], dtype=np.float32) - .5, 0,
                 np.array([w-1, h-1], dtype=np.float32))
    ij = np.floor(xy).astype(np.int32)
    other = np.minimum(ij + 1, (w-1, h-1))
    tx, ty = (xy - ij).T
    x, y = ij.T
    xx, yy = other.T
    return ((pixels[y,x] * (1-tx[:,None]) + pixels[y,xx] * tx[:,None]) * (1-ty[:,None])
            + (pixels[yy,x] * (1-tx[:,None]) + pixels[yy,xx] * tx[:,None]) * ty[:,None])


def project(uv, ids, inputs: dict[int, tuple[Path | None, object]], *, color: bool) -> np.ndarray:
    """Unassigned regions stay transparent; a constant neutral map has opaque coverage."""
    out = np.zeros((*ids.shape, 4), dtype=np.float32)
    groups = {}
    for slot, (path, scale) in inputs.items():
        groups.setdefault((path, tuple(scale) if isinstance(scale, (list, tuple)) else scale), []).append(slot)
    for (path, scale), slots in groups.items():
        image = None
        for start in range(0, len(ids), 64):
            y, x = np.nonzero(np.isin(ids[start:start+64], slots))
            if not x.size:
                continue
            y += start
            if path is None:
                out[y, x, :3], out[y, x, 3] = scale, 1
                continue
            if image is None:
                image = read_pixels(path, color)
            row = sample(image, uv[y, x])
            row[:, :3] *= scale
            out[y, x] = row
    return out
