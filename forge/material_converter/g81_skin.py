"""Identify the source figure and UV layout for Genesis 8.1 skin conversion."""

from dataclasses import dataclass
from urllib.parse import unquote


SKIN_ZONES = frozenset({
    "Face", "Lips", "Ears", "EyeSocket", "Head", "Body", "Arms", "Legs", "Fingernails", "Toenails",
})


@dataclass(frozen=True)
class G81SkinLayout:
    gender: str
    owner: str
    geometry: str
    layout: str
    uv_name: str


def _uv(gender: str, native: bool) -> str:
    folder = f"{gender} 8_1" if native else gender
    name = f"Base 8.1 {gender}" if native else f"Base {gender}"
    return f"/data/Daz 3D/Genesis 8/{folder}/UV Sets/DAZ 3D/Base/{name}.dsf#{name}"


def resolve_g81_skin_layout(document: dict) -> G81SkinLayout:
    """Resolve an explicit, uniform Base UV on the G8.1 figure, ignoring its accessories."""
    scene = document.get("scene", {})
    figures = [
        (gender, node, geometry["id"])
        for node in scene.get("nodes", ())
        for gender in ("Female", "Male")
        if unquote(node.get("id", "")).split("-", 1)[0] == f"Genesis8_1{gender}"
        for geometry in node.get("geometries", ())
        if unquote(geometry.get("id", "")).split("-", 1)[0] == f"Genesis81{gender}Geom"
    ]
    if len(figures) != 1:
        raise ValueError("Expected one native Genesis 8.1 figure with authored skin surfaces")
    gender, node, geometry = figures[0]
    covered, urls = set(), set()
    for row in scene.get("materials", ()):
        if unquote(row.get("geometry") or "") != "#" + unquote(geometry):
            continue
        zones = SKIN_ZONES.intersection(row.get("groups", ()))
        if covered.intersection(zones):
            raise ValueError("Duplicate Genesis 8.1 skin surface")
        if zones:
            covered.update(zones)
            urls.add(unquote(row.get("uv_set") or "").casefold())
    if covered != SKIN_ZONES or len(urls) != 1:
        raise ValueError("Expected the complete Genesis 8.1 skin on one explicit UV set")
    for native in (True, False):
        canonical = _uv(gender, native)
        if urls == {canonical.casefold()}:
            return G81SkinLayout(gender, unquote(node["id"]), unquote(geometry),
                                 "native" if native else "legacy", canonical.split("#", 1)[1])
    raise ValueError("Unsupported Genesis 8.1 skin UV set")


def same_local_uvs(geometry: dict, first: dict, second: dict, zones: set[str], *, tolerance=2e-6) -> bool:
    """True when the selected faces differ only by a whole UV tile."""
    data = [(uv["uvs"]["values"], {(p, v): i for p, v, i in uv["polygon_vertex_indices"]})
            for uv in (first, second)]
    groups = geometry["polygon_material_groups"]["values"]
    checked = set()
    for polygon, face in enumerate(geometry["polylist"]["values"]):
        zone = groups[face[1]]
        if zone not in zones:
            continue
        checked.add(zone)
        corners = [[values[overrides.get((polygon, v), v)] for v in face[2:]] for values, overrides in data]
        offset = tuple(round(b - a) for a, b in zip(corners[0][0], corners[1][0], strict=True))
        if any(abs(b - a - shift) > tolerance for left, right in zip(*corners, strict=True)
               for a, b, shift in zip(left, right, offset, strict=True)):
            return False
    return checked == zones
