import numpy as np

from forge.material_converter.atlas import TransferGrid, project, write_pixels
from forge.material_converter import skin_joins


def _identity_grid(size):
    p = (np.arange(size, dtype=np.float32) + .5) / size
    return np.stack(np.meshgrid(p, p), axis=-1)


def test_adaptive_lookup_samples_detail_from_the_source_not_a_resized_export(tmp_path):
    small, large = 16, 32
    grid = TransferGrid(_identity_grid(small), np.ones((small, small), np.uint8))
    high_frequency = np.ones((large, large, 4), np.float32)
    high_frequency[..., :3] = np.arange(large)[:, None, None] % 2
    image = tmp_path / "source.png"
    write_pixels(image, high_frequency, color=False)

    uv, ids = grid.at_size(large)
    result = project(uv, ids, {1: (image, 1)}, color=False)
    np.testing.assert_array_equal(result[1:-1, 1:-1], high_frequency[1:-1, 1:-1])
    assert grid.at_size(large)[0] is uv


def test_resizing_lookup_keeps_donor_ids_and_disjoint_islands_separate():
    size = 16
    uv = _identity_grid(size)
    ids = np.ones((size, size), np.uint8)
    ids[:8, 8:] = 2
    uv[:, :8, 0] = .10
    uv[:, 8:, 0] = .95
    grid = TransferGrid(uv, ids)

    resized, labels = grid.at_size(32)
    np.testing.assert_array_equal(labels[:16, 16:], 2)
    np.testing.assert_array_equal(labels[16:, 16:], 1)
    np.testing.assert_allclose(resized[:, :16, 0], .10)
    np.testing.assert_allclose(resized[:, 16:, 0], .95)
    smaller, labels = grid.at_size(8)
    np.testing.assert_allclose(smaller[:, :4, 0], .10)
    np.testing.assert_allclose(smaller[:, 4:, 0], .95)
    assert set(np.unique(labels)) == {1, 2}


def test_roughness_join_preserves_each_tiles_resolution(monkeypatch):
    sizes = {"Body": 4, "Head": 8, "Arms": 4, "Legs": 2}
    maps = {zone: np.ones((size, size, 4), np.float32) for zone, size in sizes.items()}
    for zone in ("Head", "Arms", "Legs"):
        maps[zone][..., :3] = 0
    monkeypatch.setattr(skin_joins, "paired_edges", lambda *args: [(None, None)])
    monkeypatch.setattr(skin_joins, "rasterize_regions", lambda _g, _uv, _z, size: np.ones((size, size)))

    def field(_edges, footprint):
        i = len(footprint) - 1
        return (np.array([i]), np.array([i])), np.array([[.5, .5]]), np.zeros((1, 2)), np.ones(1)

    monkeypatch.setattr(skin_joins, "boundary_lookup", field)
    result = {}
    skin_joins.reconcile_roughness(None, None, maps.__getitem__, result.__setitem__, sizes)

    for zone, size in sizes.items():
        assert result[zone].shape == (size, size, 4)
        np.testing.assert_array_equal(result[zone][-1, -1], 1)
