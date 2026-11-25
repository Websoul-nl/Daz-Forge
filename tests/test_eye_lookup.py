import numpy as np
import pytest

from forge.material_converter.eye_lookup import linear_dson_tint, pad_eye_roles, transfer_eye_band


def test_dson_tint_matches_live_daz_linear_values():
    tint = linear_dson_tint([0.0627451, 0.06666667, 0.05882353])
    assert tint == pytest.approx([0.0022629532, 0.0025858255, 0.0019634159], rel=1e-6)
    assert np.array_equal(linear_dson_tint([1, 0, 1]), [1, 0, 1])


@pytest.mark.parametrize("bad", ([0, 1], [float("nan"), 0, 0], [1.01, 0, 0], [-.1, 0, 0]))
def test_invalid_dson_tints_are_rejected(bad):
    with pytest.raises(ValueError, match="normalized DSON"):
        linear_dson_tint(bad)


def square(radius, center=(0, 0)):
    return np.asarray(center) + radius * np.array([[-1,-1], [1,-1], [1,1], [-1,1]])


def test_pupil_stays_inside_its_separate_source_island():
    points = [[0,0], [1,0], [0,1], [1,1]]
    mapped = transfer_eye_band(points, np.zeros(2), (None, square(1)), np.array([10,20]),
                               (None, square(2, (10,20))), inset=.1)
    np.testing.assert_allclose(mapped, [[10,20], [11.9,20], [10,21.9],
                                       [12-.1/np.sqrt(2),22-.1/np.sqrt(2)]])


def test_iris_avoids_the_gap_at_its_cardinal_and_diagonal_edges():
    points = [[1,0], [0,-1], [-1.5,1.5], [2,0]]
    mapped = transfer_eye_band(points, np.zeros(2), (square(1), square(2)), np.zeros(2),
                               (square(4), square(10)), inset=.25)
    np.testing.assert_allclose(mapped, [[4.25,0], [0,-4.25], [-7,7], [9.75,0]])


def test_rejects_an_inset_that_would_cross_the_iris():
    with pytest.raises(ValueError, match="too narrow"):
        transfer_eye_band([[1,0]], np.zeros(2), (square(1), square(2)), np.zeros(2),
                          (square(3), square(4)), inset=.6)


def test_role_padding_keeps_island_identity_without_wrapping():
    roles = np.zeros((5, 6), dtype=np.uint8)
    roles[0, 0] = 2
    roles[3, 4] = 3
    padded = pad_eye_roles(roles, 1)
    assert padded[0, 1] == padded[1, 0] == 2
    assert padded[3, 5] == padded[2, 4] == 3
    assert padded[4, 0] == padded[0, 5] == padded[1, 1] == 0
    assert np.count_nonzero(roles) == 2
