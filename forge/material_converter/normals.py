"""Character-independent tangent-normal transport, including mirrored UV frames."""
import numpy as np


def _unit(value):
    # Scale before squaring; retain the existing small-vector length floor.
    scale = np.maximum(np.max(np.abs(value), axis=-1, keepdims=True), 1e-12)
    scaled = value / scale
    length = np.linalg.norm(scaled, axis=-1, keepdims=True)
    return scaled / np.maximum(length, 1e-12 / scale)


def flatten_basis(vector, base):
    """Apply the shortest rotation taking the fitted geometric normal to +Z."""
    base = _unit(base)
    axis = np.stack((base[..., 1], -base[..., 0], np.zeros(base.shape[:-1])), axis=-1)
    crossed = np.cross(axis, vector)
    result = vector + crossed + np.cross(axis, crossed) / np.maximum(1 + base[..., 2:3], 1e-8)
    return np.where((base[..., 2] < -.99999)[..., None], vector * [1, -1, -1], result)


def from_calibration(flat_rgb, x_rgb, y_rgb):
    """Recover a 2D rotation/reflection from flat and 45-degree normal bakes.

    Calibration textures are constant vectors, never character skin maps. The
    returned cos/sin and handedness leave a flat normal exactly flat.
    """
    flat, x, y = (np.asarray(a, dtype=np.float32) * 2 - 1 for a in (flat_rgb, x_rgb, y_rgb))
    if flat.shape != x.shape or flat.shape != y.shape or flat.shape[-1] != 3:
        raise ValueError("Calibration arrays must have matching (..., 3) shapes")
    valid = np.ones(flat.shape[:-1], dtype=bool)
    for value in (flat, x, y):
        valid &= np.isfinite(value).all(axis=-1) & (np.abs(np.linalg.norm(value, axis=-1) - 1) < .08)
    xx = flatten_basis(x, flat)[..., :2]
    yy = flatten_basis(y, flat)[..., :2]
    valid &= (np.linalg.norm(xx, axis=-1) > .2) & (np.linalg.norm(yy, axis=-1) > .2)
    cs = _unit(xx)
    sign = np.where(xx[..., 0] * yy[..., 1] - xx[..., 1] * yy[..., 0] < 0, -1, 1).astype(np.int8)
    cs = np.where(valid[..., None], cs, np.array([1, 0], dtype=np.float32))
    return cs, sign, valid


def apply_transform(encoded, cos_sin, handedness):
    """Transform linear OpenGL-style normal RGB, returning normalized RGB."""
    encoded = np.asarray(encoded, dtype=np.float32)
    cs = np.asarray(cos_sin, dtype=np.float32)
    sign = np.asarray(handedness)
    if encoded.shape[-1] != 3 or cs.shape != (*encoded.shape[:-1], 2) or sign.shape != encoded.shape[:-1]:
        raise ValueError("Normal and transform dimensions do not match")
    if not np.isfinite(encoded).all() or not np.isfinite(cs).all() or not np.isin(sign, [-1, 1]).all():
        raise ValueError("Invalid normal or tangent transform")
    if np.any(np.linalg.norm(cs, axis=-1) < .1):
        raise ValueError("Degenerate tangent transform")
    cs = _unit(cs)
    value = encoded * 2 - 1
    x, y, z = value[..., 0], value[..., 1], value[..., 2]
    c, s = cs[..., 0], cs[..., 1]
    result = np.stack((c * x - sign * s * y, s * x + sign * c * y, z), axis=-1)
    if np.any(np.linalg.norm(result, axis=-1) < 1e-8):
        raise ValueError("Zero-length source normal")
    return _unit(result) * .5 + .5


def fade_to_flat(encoded, interior_weight):
    """Preserve donor normals at a graft edge, fading to neutral inside it."""
    encoded = np.asarray(encoded, dtype=np.float32)
    weight = np.asarray(interior_weight, dtype=np.float32)
    if encoded.shape[-1] != 3 or weight.shape != encoded.shape[:-1]:
        raise ValueError("Normal and fade dimensions do not match")
    if (not np.isfinite(encoded).all() or not np.isfinite(weight).all()
            or np.any((weight < 0) | (weight > 1))):
        raise ValueError("Invalid seam normal or fade weight")
    normal = encoded * 2 - 1
    if np.any(np.linalg.norm(normal, axis=-1) < 1e-8):
        raise ValueError("Zero-length source normal")
    result = _unit(normal) * (1 - weight[..., None])
    result[..., 2] += weight
    if np.any(np.linalg.norm(result, axis=-1) < 1e-8):
        raise ValueError("Degenerate seam normal blend")
    return _unit(result) * .5 + .5


def bump_to_normal(height, strength):
    """Encode unscaled two-neighbor bump differences as tangent normals.

    Rows run bottom-up (increasing V); edges repeat. Strength multiplies
    h[i+1] - h[i-1] on each axis, without a 0.5 factor: this is not a true
    per-pixel derivative or physical displacement distance. The convention
    approximates MDL file_bump_texture, not exact Iray filtering. Compute
    differences before UV transfer.
    """
    height = np.asarray(height, dtype=np.float32)
    scale = np.asarray(strength, dtype=np.float32)
    if (height.ndim != 2 or min(height.shape) < 2 or scale.ndim != 0
            or not np.isfinite(height).all() or not np.isfinite(scale)):
        raise ValueError("Expected a finite height image and scalar strength")
    dx = np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)
    dy = np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)
    result = np.stack((-scale * dx, -scale * dy, np.ones_like(height)), axis=-1)
    if not np.isfinite(result).all():
        raise ValueError("Bump slopes exceed finite range")
    return _unit(result) * .5 + .5


def combine_normals(base, detail):
    """Compose encoded tangent normals by reorienting detail onto the base."""
    base, detail = (np.asarray(value, dtype=np.float32) for value in (base, detail))
    if (base.ndim < 1 or base.shape != detail.shape or base.shape[-1] != 3
            or not np.isfinite(base).all() or not np.isfinite(detail).all()):
        raise ValueError("Expected matching finite (..., 3) normal arrays")
    base, detail = base * 2 - 1, detail * 2 - 1
    if any(np.any(np.linalg.norm(n, axis=-1) < 1e-8) for n in (base, detail)):
        raise ValueError("Zero-length source normal")
    t = _unit(base).copy()
    t[..., 2] += 1
    if np.any(t[..., 2] < 1e-6):
        raise ValueError("Reoriented blend is singular at a downward base normal")
    u = _unit(detail) * [-1, -1, 1]
    result = t * (np.sum(t * u, axis=-1) / t[..., 2])[..., None] - u
    return _unit(result) * .5 + .5
