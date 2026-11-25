import numpy as np
import pytest

from forge.material_converter.uv_lookup import decode_uv_lookup


def test_normalized_float_coordinates_do_not_collapse_to_a_corner():
    uv = np.array([[[.25, .75], [.125, .9375]]], dtype=np.float32)
    np.testing.assert_array_equal(decode_uv_lookup(uv), uv)


def test_uint16_lookup_is_normalized_exactly_once():
    uv = np.array([[[0, 65535], [16384, 49151]]], dtype=np.uint16)
    np.testing.assert_allclose(decode_uv_lookup(uv), uv.astype(np.float32) / 65535)


@pytest.mark.parametrize("uv", [
    np.array([[[.5, np.nan]]]), np.array([[[.5, 1.1]]]),
    np.zeros((2, 2), dtype=np.float32), np.zeros((2, 2, 2), dtype=np.uint8),
])
def test_bad_cache_is_not_silently_clipped(uv):
    with pytest.raises(ValueError):
        decode_uv_lookup(uv)
