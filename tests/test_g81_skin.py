from copy import deepcopy
from urllib.parse import quote

import pytest

from forge.material_converter.g81_skin import G81SkinLayout, SKIN_ZONES, resolve_g81_skin_layout, same_local_uvs


def preset(gender, *, native):
    owner = f"Genesis8_1{gender}"
    geometry = f"Genesis81{gender}Geom"
    folder = f"{gender} 8_1" if native else gender
    uv_name = f"Base 8.1 {gender}" if native else f"Base {gender}"
    url = f"/data/DAZ 3D/Genesis 8/{folder}/UV Sets/Daz 3D/Base/{uv_name}.dsf#{uv_name}"
    return {"scene": {
        "nodes": [{"id": owner, "geometries": [{"id": geometry}]},
                  {"id": "Overlay", "geometries": [{"id": "OverlayGeometry"}]}],
        "materials": [{"geometry": "#OverlayGeometry", "groups": ["Head", "Body", "Face"]},
                      *({"geometry": f"#{geometry}", "groups": [zone], "uv_set": quote(url, safe="/#")}
                        for zone in sorted(SKIN_ZONES))],
    }}


@pytest.mark.parametrize("gender", ["Male", "Female"])
@pytest.mark.parametrize("native", [False, True])
def test_read_uv_independently_of_figure_generation(gender, native):
    document = preset(gender, native=native)
    assert resolve_g81_skin_layout(document) == G81SkinLayout(
        gender, f"Genesis8_1{gender}", f"Genesis81{gender}Geom", "native" if native else "legacy",
        f"Base 8.1 {gender}" if native else f"Base {gender}",
    )


@pytest.mark.parametrize("problem", ["mixed", "unknown", "omitted", "old figure", "duplicate surface", "two figures"])
def test_reject_ambiguous_or_incomplete_layout(problem):
    document = preset("Female", native=True)
    scene = document["scene"]
    if problem == "mixed":
        scene["materials"][-1]["uv_set"] = preset("Female", native=False)["scene"]["materials"][-1]["uv_set"]
    elif problem == "unknown":
        for material in scene["materials"][1:]:
            material["uv_set"] = "/Custom/Base%208.1%20Female.dsf#Base%208.1%20Female"
    elif problem == "omitted":
        scene["materials"] = scene["materials"][:-1]
    elif problem == "old figure":
        scene["nodes"][0]["id"] = "Genesis8Female"
    elif problem == "duplicate surface":
        scene["materials"].append(deepcopy(scene["materials"][-1]))
    else:
        scene["nodes"].extend(preset("Male", native=True)["scene"]["nodes"][:1])
    with pytest.raises(ValueError):
        resolve_g81_skin_layout(document)


def test_fitted_lookup_reuse_requires_same_face_corner_coordinates():
    geo = {"polygon_material_groups": {"values": ["Toenails"]},
           "polylist": {"values": [[0, 0, 0, 1, 2]]}}
    old = {"uvs": {"values": [[.1, .2], [.4, .2], [.3, .7]]}, "polygon_vertex_indices": []}
    new = {"uvs": {"values": [[1.1, .2], [1.4, .2], [1.3, .7]]}, "polygon_vertex_indices": []}
    assert same_local_uvs(geo, old, new, {"Toenails"})
    assert not same_local_uvs(geo, old, new, {"Head"})
    new["uvs"]["values"].append([1.3, .71])
    new["polygon_vertex_indices"].append([0, 2, 3])
    assert not same_local_uvs(geo, old, new, {"Toenails"})
