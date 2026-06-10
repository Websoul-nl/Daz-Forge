# Pose Converter Design

## Goal

Add a Daz Forge `Pose Converters` tool that converts a DIM pose product made for Genesis 8 Female into a new Genesis 9 pose product without using Daz Studio for the batch loop.

The first target sample is:

`D:\Software projects\daz-forge\.codex-local\dim-samples\IM00083577-01_RoadTripPosesforGenesis8Female.zip`

The calibration output is:

`D:\Software projects\daz-forge\.codex-local\dim-samples\Road Trip 01 G9.duf`

## Product Shape

V1 accepts a single DIM zip or unpacked DIM product. It finds pose `.duf` files under `Content/People/Genesis 8 Female/Poses/...`, converts them to lean Genesis 9 `.duf` pose files, copies matching `.duf.png` and `.tip.png` thumbnails, and writes an output folder. Packaging the converted folder as a DIM zip can reuse the existing packager once the converter core is validated.

V1 does not launch Daz Studio. Daz Studio is used only for manual visual validation of selected converted poses.

## Conversion Strategy

Read each `.duf` as JSON, decompressing gzip when needed. Convert `scene.animations` entries by parsing URLs like:

`name://@selection/lShin:?rotation/x/value`

The converter emits only meaningful pose entries, not DAZ's full default state. It skips zero rotations/translations and scale values equal to `1`.

The mapping table converts G8F bone/channel/property combinations into G9 bone/channel/property combinations. Most values copy directly; some apply offsets or merge channels. Road Trip 01 already shows examples:

- `lShin rotation/x -> l_shin rotation/x`, same value
- `lThighBend rotation/x -> l_thigh rotation/x`, same value
- `lThighTwist rotation/y -> l_thigh rotation/y`, same value
- `lThighBend rotation/z -> l_thigh rotation/z`, value plus `6.0`
- `lForearmBend rotation/y -> l_forearm rotation/y`, same value
- `lForearmTwist rotation/x -> l_forearm rotation/x`, same value
- `lShldrBend -> l_upperarm`
- `lShldrTwist -> l_upperarm`
- `lCollar -> l_shoulder`

The initial table should focus on body, arms, legs, hands, and head/neck. Face rig mappings can follow after the body converter passes sample validation, because the PoseTransfer script contains several averaged face mappings.

## Architecture

Add a focused conversion core under `forge/pose_converter/`:

- `duf.py`: load/save plain or gzip `.duf`, preserve JSON structure.
- `mapping.py`: G8F to G9 mapping rules and offset functions.
- `converter.py`: convert one pose object and return conversion diagnostics.
- `product.py`: scan a DIM zip/folder, convert pose files, copy thumbnails, and write an output folder.

Add tests under `tests/` using the Road Trip sample and the saved G9 calibration file. Tests should compare meaningful animation entries rather than raw file equality, because DAZ writes many default values that the lean converter intentionally omits.

Add the UI tab after the conversion core works. The tab should show source product, pose count, output folder, conversion warnings, and a simple `Convert` button.

## Validation

Automated tests compare converted Road Trip 01 against the saved G9 DUF:

- same important target bones/channels
- same values for direct mappings
- expected offsets for known special mappings
- no bloated default scale/rotation entries

Manual validation: install or load a few converted poses in Daz Studio on Genesis 9 and visually compare against the DAZ-converted calibration pose.

## Out Of Scope For V1

- Perfect face rig conversion.
- Driving Daz Studio in batch mode.
- Converting non-G8F source figures.
- Converting prop poses or wearable-specific poses.
- Final DIM metadata polish beyond what existing Daz Forge packager can already produce.
