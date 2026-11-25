import numpy as np
import pytest
from forge.material_converter.regions import rasterize_regions


def fixtures():
    geometry={'polygon_material_groups':{'values':['Lips']},'polylist':{'values':[[0,0,0,1,2,3]]}}
    uv={'polygon_vertex_indices':[],'uvs':{'values':[[0,0],[1,0],[1,1],[0,1]]}}
    return geometry,uv


def test_quad_covers_whole_atlas():
    g,u=fixtures()
    np.testing.assert_array_equal(rasterize_regions(g,u,{'Lips':.25},4),np.full((4,4),.25))


def test_uv_override_and_tile_offset():
    g,u=fixtures();u['uvs']['values']=[[2,0],[3,0],[3,1],[2,1],[2.5,0]]
    u['polygon_vertex_indices']=[[0,0,4]]
    result=rasterize_regions(g,u,{'Lips':1},4)
    assert result[0,0]==0
    assert result[-1,0]==1


def test_other_regions_and_invalid_values():
    g,u=fixtures()
    assert not rasterize_regions(g,u,{},4).any()
    with pytest.raises(ValueError):rasterize_regions(g,u,{'Lips':np.nan},4)
