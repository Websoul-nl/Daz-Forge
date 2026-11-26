# Genesis 8 to Genesis 9 UV transfers

Each folder is one conversion to Genesis 9 Base Multi UDIM. The two
Genesis 8.1 layout families are distinct, even for the same figure.

| Figure | Source UV | Bundle folder |
| --- | --- | --- |
| G8 Female | Base Female | `g8-base-female-to-g9` |
| G8 Male | Base Male | `g8-base-male-to-g9` |
| G8.1 Female | Base Female | `g8-1-legacy-female-to-g9` |
| G8.1 Male | Base Male | `g8-1-legacy-male-to-g9` |
| G8.1 Female | Base 8.1 Female | `g8-1-native-female-to-g9` |
| G8.1 Male | Base 8.1 Male | `g8-1-native-male-to-g9` |

A bundle contains `manifest.json`, with paths relative to that manifest,
and `<part>_uv.npz` files. An optional `<part>_tangent.npz` is paired with
its exact lookup and lets Iray Uber retain source normal detail. Without
calibration, the exporter reports omitted source normals. PBRSkin uses
native G9 detail instead. Both nail surfaces share a single nail atlas. Only
G8 Base Female has a verified nail tangent transform today. Its main maps are
4K; the other layouts were calibrated at 2K.

Locally prepared NPZ files contain numeric UV lookup and calibration
arrays derived from installed figure geometry and UVs, not character
textures or source figure files. They are ignored by Git pending
redistribution clearance. Private builds with these files staged include
the manifests and NPZs as package data. Build public artifacts from a clean
checkout, and verify that the wheel and source archive contain no NPZs unless
redistribution has been cleared. A checkout without the binaries can point to
a complete local bundle using the override. For private release verification,
compare the payloads against the SHA-256 inventory in each manifest.
