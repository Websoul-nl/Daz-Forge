import numpy as np
import pytest

from forge.material_converter.normals import (
    _unit, apply_transform, from_calibration, fade_to_flat, bump_to_normal, combine_normals,
)


def test_unit_normalization_preserves_zero_and_tiny_vector_behavior():
    result = _unit(np.array([[0., 0., 0.], [1e-15, 0., 0.]], dtype=np.float32))
    np.testing.assert_allclose(result, [[0., 0., 0.], [.001, 0., 0.]], atol=1e-9)


def test_identity_and_unit_length():
    normal = np.array([[.8,.5,.9],[.5,.5,1]],dtype=np.float32)
    result = apply_transform(normal,np.array([[1,0],[1,0]]),np.array([1,1]))
    vector = normal*2-1
    vector /= np.linalg.norm(vector,axis=-1,keepdims=True)
    np.testing.assert_allclose(result,vector*.5+.5,atol=1e-6)


def test_rotation_and_uv_handedness():
    normal = np.array([[1,.5,.5],[.5,1,.5]],dtype=np.float32)
    result = apply_transform(normal,np.array([[0,1],[1,0]]),np.array([1,-1]))
    np.testing.assert_allclose(result,[[.5,1,.5],[.5,0,.5]],atol=1e-6)


def test_flat_normal_is_invariant():
    phase = np.linspace(-np.pi,np.pi,200)
    cs = np.column_stack((np.cos(phase),np.sin(phase)))
    result = apply_transform(np.tile([.5,.5,1],(200,1)),cs,np.where(phase<0,-1,1))
    np.testing.assert_allclose(result,np.tile([.5,.5,1],(200,1)),atol=1e-6)


def test_calibration_recovers_rotation_and_mirror():
    q = np.sqrt(.5)
    flat = np.array([[.5,.5,1],[.5,.5,1]])
    x = np.array([[.5,q*.5+.5,q*.5+.5],[q*.5+.5,.5,q*.5+.5]])
    y = np.array([[-q*.5+.5,.5,q*.5+.5],[.5,-q*.5+.5,q*.5+.5]])
    cs, sign, valid = from_calibration(flat,x,y)
    assert valid.all()
    np.testing.assert_allclose(cs,[[0,1],[1,0]],atol=1e-6)
    np.testing.assert_array_equal(sign,[1,-1])


def test_missing_bake_coverage_is_not_silently_accepted():
    cs, sign, valid = from_calibration(np.zeros((1,3)),np.zeros((1,3)),np.zeros((1,3)))
    assert not valid.any()
    assert np.isfinite(cs).all()


def test_invalid_transform_rejected():
    with pytest.raises(ValueError):
        apply_transform(np.array([[.5,.5,1]]),np.array([[np.nan,1]]),np.array([1]))
    with pytest.raises(ValueError):
        apply_transform(np.array([[.5,.5,1]]),np.array([[1,0]]),np.array([0]))


def test_seam_normal_fade_preserves_boundary_and_neutral_interior():
    normal=np.tile([.8,.5,.9],(3,1))
    result=fade_to_flat(normal,np.array([0,.5,1]))
    np.testing.assert_allclose(result[0],[.8,.5,.9],atol=1e-6)
    np.testing.assert_allclose(result[2],[.5,.5,1],atol=1e-6)
    np.testing.assert_allclose(np.linalg.norm(result*2-1,axis=1),1,atol=1e-6)
    assert .5<result[1,0]<.8


@pytest.mark.parametrize('weight',[-.01,1.01,np.nan,np.inf])
def test_seam_normal_fade_rejects_invalid_weights(weight):
    with pytest.raises(ValueError):fade_to_flat(np.array([[.5,.5,1]]),np.array([weight]))


def test_seam_normal_fade_rejects_shape_and_nonfinite_pixels():
    with pytest.raises(ValueError):fade_to_flat(np.array([[.5,.5,1]]),np.array([0,1]))
    with pytest.raises(ValueError):fade_to_flat(np.array([[np.nan,.5,1]]),np.array([.5]))


def test_bump_constant_and_zero_strength_are_flat():
    expected=np.tile([.5,.5,1],(4,5,1))
    np.testing.assert_allclose(bump_to_normal(np.full((4,5),.7),5),expected)
    np.testing.assert_allclose(bump_to_normal(np.arange(20).reshape(4,5),0),expected)


def test_bump_slopes_use_unscaled_differences_and_bottom_up_rows():
    y,x=np.mgrid[:5,:6]
    result=bump_to_normal(.1*x+.2*y,2)[1:-1,1:-1]*2-1
    expected=np.array([-.4,-.8,1]);expected/=np.linalg.norm(expected)
    np.testing.assert_allclose(result,np.broadcast_to(expected,result.shape),atol=1e-6)


@pytest.mark.parametrize('height_scale,strength', [(1, 1e20), (1, -1e20), (1, 1e38), (1e20, 1)])
def test_bump_huge_finite_slopes_remain_unit_normals(height_scale, strength):
    height = np.tile([0., .5, 1., .5], (4, 1)) * height_scale
    with np.errstate(over='raise', invalid='raise', divide='raise'):
        result = bump_to_normal(height, strength) * 2 - 1
    assert np.isfinite(result).all()
    np.testing.assert_allclose(np.linalg.norm(result, axis=-1), 1, atol=1e-6)
    expected = np.array([-height_scale * strength, 0., 1.])
    expected /= np.linalg.norm(expected)
    np.testing.assert_allclose(result[1, 1], expected, atol=1e-6)


@pytest.mark.parametrize('shape', [(3, 4), (2, 4), (3, 2), (2, 2)])
def test_bump_repeats_neighbors_at_all_edges(shape):
    height = np.arange(np.prod(shape), dtype=np.float32).reshape(shape) ** 2 / 17
    strength = .7
    expected = np.empty((*shape, 3))
    for row in range(shape[0]):
        for col in range(shape[1]):
            dx = height[row, (col + 1) % shape[1]] - height[row, (col - 1) % shape[1]]
            dy = height[(row + 1) % shape[0], col] - height[(row - 1) % shape[0], col]
            normal = np.array([-strength * dx, -strength * dy, 1.])
            expected[row, col] = normal / np.linalg.norm(normal)
    np.testing.assert_allclose(bump_to_normal(height, strength) * 2 - 1, expected, atol=1e-6)


@pytest.mark.parametrize('height,strength',[
    (np.ones(4),1),(np.ones((1,3)),1),(np.full((2,2),np.nan),1),
    (np.ones((2,2)),np.inf),(np.ones((2,2)),[1,2]),
])
def test_bump_rejects_invalid_input(height,strength):
    with pytest.raises(ValueError):bump_to_normal(height,strength)


def test_normal_composition_preserves_identity_and_unit_length():
    detail=np.array([[.8,.5,.9],[.5,.8,.9]])
    flat=np.tile([.5,.5,1],(2,1))
    np.testing.assert_allclose(combine_normals(flat,detail),detail,atol=1e-6)
    np.testing.assert_allclose(combine_normals(detail,flat),detail,atol=1e-6)
    result=combine_normals(detail,detail)
    np.testing.assert_allclose(np.linalg.norm(result*2-1,axis=-1),1,atol=1e-6)
    assert (result[:,:2]>=detail[:,:2]).all()


def test_noncollinear_composition_matches_rotation_and_preserves_order():
    base = np.array([.8, .5, .9])
    detail = np.array([.5, .8, .9])
    np.testing.assert_allclose(combine_normals(base, detail), [.74, .8, .82], atol=1e-6)
    np.testing.assert_allclose(combine_normals(detail, base), [.8, .74, .82], atol=1e-6)


@pytest.mark.parametrize('base,detail',[
    ([[.5,.5,1]],[[.5,1]]),([[np.nan,.5,1]],[[.5,.5,1]]),
    ([[.5,.5,.5]],[[.5,.5,1]]),([[.5,.5,0]],[[.5,.5,1]]),
    ([[.5,.5,1]],[[.5,.5,.5]]),([[.5,.5,1]],[[np.nan,.5,1]]),
    ([[.5,.5,1]],[[np.inf,.5,1]]),([[.5,.5,1]],0),
])
def test_composition_rejects_invalid_normals(base,detail):
    with pytest.raises(ValueError):combine_normals(base,detail)
