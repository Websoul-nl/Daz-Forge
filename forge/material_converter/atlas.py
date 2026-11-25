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
        ys, xs = np.nonzero(np.isin(ids, slots))
        if path is None:
            out[ys, xs, :3], out[ys, xs, 3] = scale, 1
            continue
        image = read_pixels(path, color)
        for start in range(0, len(xs), 250_000):
            y, x = ys[start:start+250_000], xs[start:start+250_000]
            row = sample(image, uv[y, x])
            row[:, :3] *= scale
            out[y, x] = row
    return out
