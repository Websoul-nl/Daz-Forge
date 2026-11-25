import numpy as np

from forge.material_converter.uv_seams import boundary_lookup, paired_edges


def test_shared_face_edge_pairs_follow_vertex_order_across_uv_tiles():
    geo = {"polygon_material_groups":{"values":["Body","Arm"]},
           "polylist":{"values":[[0,0,0,1,2],[0,1,1,0,3]]}}
    uv = {"uvs":{"values":[[.2,.3],[.6,.3],[.3,.55],[2.5,.75],[2.2,.65],[2.6,.65]]},
          "polygon_vertex_indices":[[1,0,4],[1,1,5]]}
    [(body,arm)] = paired_edges(geo,uv,"Body","Arm")
    np.testing.assert_allclose(body[0],[[.2,.3],[.6,.3]])
    np.testing.assert_allclose(arm[0],[[.2,.65],[.6,.65]])


def test_lookup_feathers_only_within_the_atlas_boundary_band():
    body = (np.array([[.25,.25],[.75,.25]]),np.array([.5,.1]))
    arm = (np.array([[.25,.5],[.75,.5]]),np.array([.5,.8]))
    mask = np.zeros((64,64),dtype=bool)
    mask[32:] = True
    (y,x),source,inward,weights = boundary_lookup([(body,arm)],mask,width=12,padding=4)
    chosen = x==32
    np.testing.assert_allclose(source[chosen,1],.25)
    np.testing.assert_allclose(inward[chosen],np.tile([0,-1],(int(chosen.sum()),1)))
    point = dict(zip(y[chosen],weights[chosen],strict=True))
    assert point[31] == point[32] == 1
    assert 0 < point[40] < point[35] < 1
    assert 27 not in point and 44 not in point
