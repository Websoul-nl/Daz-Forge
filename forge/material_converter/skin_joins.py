"""Narrow PBRSkin roughness equalization across atlas tiles."""

import numpy as np

from .atlas import sample
from .regions import rasterize_regions
from .uv_seams import boundary_lookup, paired_edges


def _strip(image, donor, field):
    (y, x), points, inward, weights = field
    target = sample(donor, points + inward * (.25 / len(donor)))
    for step in (1, 2, 4, 8):
        holes = target[:, 3] < .995
        if not holes.any():
            break
        target[holes] = sample(donor, points[holes] + inward[holes] * (step / len(donor)))
    valid = target[:, 3] >= .995
    if not valid.size or valid.mean() < .985:
        raise ValueError("Too many missing donor pixels to align the roughness join")
    target[valid, 3] = 1
    result = image.copy()
    t = np.where(image[y,x,3] > .995, weights, 1)[valid,None]
    yy, xx = y[valid], x[valid]
    result[yy,xx] = image[yy,xx] * (1-t) + target[valid] * t
    return result


def reconcile_roughness(geometry, uv_set, load, save, sizes):
    """Align the narrow neighboring edges to Body without changing scalar settings."""
    zones = ("Head", "Arms", "Legs")
    edges = {z: paired_edges(geometry, uv_set, "Body", z) for z in zones}
    if not all(edges.values()):
        raise ValueError("Could not identify all Body roughness joins")

    def field(zone, pairs):
        return boundary_lookup(pairs, rasterize_regions(geometry, uv_set, {zone:1}, sizes[zone]) > 0)

    body = load("Body")
    donor = _strip(body, body, field("Body", [(a,a) for pairs in edges.values() for a,_ in pairs]))
    save("Body", donor)
    for zone in zones:
        save(zone, _strip(load(zone), donor, field(zone, edges[zone])))


def reconcile_head_weight(image, geometry, uv_set):
    """Keep authored face weight while matching a neutral neighboring Body."""
    size = len(image)
    if image.shape != (size, size, 4):
        raise ValueError("Expected a square Head weight map")
    edges = paired_edges(geometry, uv_set, "Body", "Head")
    if not edges:
        raise ValueError("Could not identify the Body / Head join")
    footprint = rasterize_regions(geometry, uv_set, {"Head":1}, size) > 0
    field = boundary_lookup(edges, footprint)
    return _strip(image, np.ones((4,4,4), np.float32), field)
