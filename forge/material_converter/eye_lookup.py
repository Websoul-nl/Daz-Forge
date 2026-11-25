"""Transfer concentric eye UV bands without crossing source island boundaries."""
import numpy as np


def linear_dson_tint(rgb):
    """Decode a stored DAZ material color before multiplying linear texture pixels."""
    encoded = np.asarray(rgb, dtype=np.float64)
    if encoded.shape != (3,) or not np.isfinite(encoded).all() or np.any((encoded < 0) | (encoded > 1)):
        raise ValueError("Expected three normalized DSON color components")
    # This is DAZ's material swatch transfer, not the sRGB image transfer curve.
    return encoded ** 2.2


def pad_eye_roles(roles, pixels=12):
    """Extend atlas role labels with the same four-neighbor order as UV padding."""
    padded = np.array(roles, copy=True)
    for _ in range(pixels):
        previous = padded.copy()
        for offset, axis in ((-1, 0), (1, 0), (-1, 1), (1, 1)):
            shifted = np.roll(previous, offset, axis=axis)
            end = 0 if offset == 1 else -1
            if axis == 0:
                shifted[end] = 0
            else:
                shifted[:, end] = 0
            take = (padded == 0) & (shifted != 0)
            padded[take] = shifted[take]
    return padded


def radial_distance(points, center, boundary):
    """Intersect outward rays with an ordered, star-shaped polygon."""
    directions = np.asarray(points) - center
    lengths = np.linalg.norm(directions, axis=-1)
    rays = directions / np.where(lengths > 0, lengths, 1)[..., None]
    rays[lengths == 0] = (1, 0)
    a = np.asarray(boundary) - center
    edges = np.roll(a, -1, axis=0) - a
    distance = np.full(lengths.shape, np.inf)
    for (x, y), (dx, dy) in zip(a, edges, strict=True):
        den = rays[..., 0]*dy - rays[..., 1]*dx
        nonparallel = np.abs(den) > 1e-12
        t = np.divide(x*dy - y*dx, den, out=np.zeros_like(den), where=nonparallel)
        fraction = np.divide(x*rays[..., 1] - y*rays[..., 0], den,
                             out=np.zeros_like(den), where=nonparallel)
        distance = np.minimum(distance, np.where(
            nonparallel & (t > 0) & (fraction >= -1e-8) & (fraction <= 1+1e-8), t, np.inf,
        ))
    if not np.isfinite(distance).all():
        raise ValueError("An eye UV ray missed its boundary")
    return rays, lengths, distance


def transfer_eye_band(points, target_center, target_boundaries, source_center,
                      source_boundaries, *, inset):
    """Map a disk (inner=None) or annulus to its corresponding source island.

    The source is inset for bilinear filtering. Different bands may have
    different source centers, even when they touch in the target atlas.
    """
    t_inner, t_outer = target_boundaries
    s_inner, s_outer = source_boundaries
    rays, radius, outer = radial_distance(points, target_center, t_outer)
    inner = 0 if t_inner is None else radial_distance(points, target_center, t_inner)[2]
    source_points = source_center + rays
    hi = radial_distance(source_points, source_center, s_outer)[2] - inset
    lo = 0 if s_inner is None else radial_distance(source_points, source_center, s_inner)[2] + inset
    if np.any(outer <= inner) or np.any(hi <= lo):
        raise ValueError("Eye UV band is inverted or too narrow for the inset")
    fraction = np.clip((radius-inner)/(outer-inner), 0, 1)
    return source_center + rays * (lo + fraction*(hi-lo))[..., None]
