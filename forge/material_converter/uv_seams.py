"""Pair texture coordinates along actual edges shared by two material zones."""

import numpy as np


def paired_edges(geometry, uv_set, first, second):
    groups = geometry["polygon_material_groups"]["values"]
    values = uv_set["uvs"]["values"]
    overrides = {(p,v):i for p,v,i in uv_set["polygon_vertex_indices"]}
    edges = {}
    for i, face in enumerate(geometry["polylist"]["values"]):
        zone = groups[face[1]]
        if zone not in (first,second):
            continue
        vertices = face[2:]
        uv = np.array([values[overrides.get((i,v),v)] for v in vertices],dtype=np.float64)
        uv -= np.floor(uv.mean(axis=0))
        for j,a in enumerate(vertices):
            k = (j+1) % len(vertices)
            b = vertices[k]
            uv_edge = uv[[j,k] if a<b else [k,j]]
            edges.setdefault(tuple(sorted((a,b))),{})[zone] = (uv_edge,uv.mean(axis=0))
    return [(e[first],e[second]) for e in edges.values() if first in e and second in e]


def _toward_face(segment, center):
    direction = segment[1]-segment[0]
    length = np.linalg.norm(direction)
    if length <= 1e-8:
        raise ValueError("Degenerate UV edge")
    normal = np.array([-direction[1],direction[0]]) / length
    return normal if normal @ (center-segment[0]) >= 0 else -normal


def boundary_lookup(pairs, footprint, *, width=16, padding=4):
    """Map a narrow target strip to matching source edges, preferring the nearest edge."""
    size = len(footprint)
    if footprint.shape != (size,size) or not 1 < padding < width:
        raise ValueError("Expected a square atlas and a bounded texture strip")
    distances = np.full(footprint.shape,np.inf,dtype=np.float32)
    source_uv = np.zeros((*footprint.shape,2),dtype=np.float32)
    inward = np.zeros_like(source_uv)
    for (source,source_center),(target,target_center) in pairs:
        segment = target*size-.5
        dv = segment[1]-segment[0]
        if dv @ dv <= 1e-8:
            continue
        lo = np.maximum(0,np.floor(segment.min(axis=0)-width).astype(int))
        hi = np.minimum(size-1,np.ceil(segment.max(axis=0)+width).astype(int))
        x,y = np.meshgrid(np.arange(lo[0],hi[0]+1),np.arange(lo[1],hi[1]+1))
        points = np.stack((x,y),axis=-1)-segment[0]
        t = np.clip(points@dv/(dv@dv),0,1)
        dist = np.linalg.norm(points-t[...,None]*dv,axis=-1)
        take = (dist<np.where(footprint[y,x],width,padding)) & (dist<distances[y,x])
        xx,yy = x[take],y[take]
        distances[yy,xx] = dist[take]
        source_uv[yy,xx] = source[0] + t[take,None]*(source[1]-source[0])
        inward[yy,xx] = _toward_face(source,source_center)
    active = np.isfinite(distances)
    t = np.clip((distances[active]-1.5)/(width-1.5),0,1)
    weights = 1 - t*t*(3-2*t)
    weights[~footprint[active]] = 1
    return np.nonzero(active),source_uv[active],inward[active],weights
