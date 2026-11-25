"""Rasterize source material-zone masks for surfaces merged in another generation."""
import math
import numpy as np


def rasterize_regions(geometry, uv_set, values, size):
    """Return a bottom-up scalar atlas; selected material names must share an atlas."""
    if not isinstance(size, int) or size < 1:
        raise ValueError("Invalid atlas size")
    result = np.zeros((size,size),dtype=np.float32)
    groups = geometry['polygon_material_groups']['values']
    overrides = {(poly,vertex):uv for poly,vertex,uv in uv_set['polygon_vertex_indices']}
    uvs = uv_set['uvs']['values']
    for index, face in enumerate(geometry['polylist']['values']):
        group = groups[face[1]]
        if group not in values:
            continue
        value = float(values[group])
        if not math.isfinite(value):
            raise ValueError("Non-finite region value")
        corners = np.array([uvs[overrides.get((index,v),v)] for v in face[2:]],dtype=np.float64)
        corners -= np.floor(corners.mean(axis=0))
        corners = corners * size - .5
        for i in range(1,len(corners)-1):
            uv = corners[[0,i,i+1]]
            low=np.maximum(np.ceil(uv.min(axis=0)).astype(int),0)
            high=np.minimum(np.floor(uv.max(axis=0)).astype(int),size-1)
            if np.any(high<low):
                continue
            den=(uv[1,0]-uv[0,0])*(uv[2,1]-uv[0,1])-(uv[1,1]-uv[0,1])*(uv[2,0]-uv[0,0])
            if abs(den)<1e-12:
                continue
            x,y=np.meshgrid(np.arange(low[0],high[0]+1),np.arange(low[1],high[1]+1))
            dx,dy=x-uv[0,0],y-uv[0,1]
            a=(dx*(uv[2,1]-uv[0,1])-dy*(uv[2,0]-uv[0,0]))/den
            b=((uv[1,0]-uv[0,0])*dy-(uv[1,1]-uv[0,1])*dx)/den
            inside=(a>=-1e-7)&(b>=-1e-7)&(a+b<=1+1e-7)
            result[y[inside],x[inside]]=value
    return result
