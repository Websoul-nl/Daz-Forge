# Bidirectional Pose Converter Design

## Goal

Extend the Pose Converters tool so it can convert pose products both from Genesis 8 to Genesis 9 and from Genesis 9 back to Genesis 8 target layouts.

## User Model

Genesis 8 and Genesis 9 are asymmetric library targets:

- Genesis 8 has distinct Female and Male pose folders, plus a useful merged `People/Genesis 8/Poses/...` convention.
- Genesis 9 has a single target pose folder.

The UI should expose conversion presets rather than raw technical directions.

## Conversion Presets

The Pose Converters page gets one dropdown with these choices:

- `Genesis 8 -> Genesis 9`
- `Genesis 9 -> Genesis 8 Female`
- `Genesis 9 -> Genesis 8 Male`
- `Genesis 9 -> Genesis 8 Female + Male`
- `Genesis 9 -> Genesis 8 Merged`

The existing behavior becomes `Genesis 8 -> Genesis 9`.

## Path Behavior

For `Genesis 8 -> Genesis 9`:

- Convert pose files found under `People/Genesis 8 Female/Poses/...`.
- Convert pose files found under `People/Genesis 8 Male/Poses/...`.
- Write outputs under `People/Genesis 9/Poses/...`.
- If both source variants would produce the same output path, suffix file stems with `_F` and `_M`.

For `Genesis 9 -> Genesis 8 Female`:

- Convert pose files found under `People/Genesis 9/Poses/...`.
- Write outputs under `People/Genesis 8 Female/Poses/...`.

For `Genesis 9 -> Genesis 8 Male`:

- Convert pose files found under `People/Genesis 9/Poses/...`.
- Write outputs under `People/Genesis 8 Male/Poses/...`.

For `Genesis 9 -> Genesis 8 Female + Male`:

- Convert each Genesis 9 pose once.
- Write one copy under `People/Genesis 8 Female/Poses/...`.
- Write one copy under `People/Genesis 8 Male/Poses/...`.

For `Genesis 9 -> Genesis 8 Merged`:

- Convert pose files found under `People/Genesis 9/Poses/...`.
- Write outputs under `People/Genesis 8/Poses/...`.
- Product and path naming should use `Genesis 8`, not `Genesis 8 Female`.

## Bone Mapping

The implementation should use explicit conversion direction objects. The current G8F to G9 mapping remains available for Genesis 8 Female and Genesis 8 Male inputs because their pose bone names match for this workflow.

The reverse G9 to G8 mapping must be deliberate rather than a blind inversion:

- Direct one-to-one bones can be inverted.
- Existing thigh Z offsets are inverted.
- G9 `l_upperarm` and `r_upperarm` map to G8 shoulder bend channels.
- G9 `l_forearm` and `r_forearm` map to G8 forearm bend channels.
- Root selection and hip transforms are preserved.
- Channels that cannot be mapped confidently are reported as unmapped.

## Product Metadata

Converted package names and support metadata should follow the selected preset:

- `Genesis 8 -> Genesis 9` replaces G8 figure labels with `Genesis 9`.
- Female and Male G8 targets replace `Genesis 9` with `Genesis 8 Female` or `Genesis 8 Male`.
- Merged G8 target replaces `Genesis 9` with `Genesis 8`.

User-entered store, code, token, GUID, artists, and product image behavior remain unchanged.

## UI Behavior

The Pose Converters page adds the conversion preset dropdown near the source selector. The source placeholder and generated product name should reflect the selected preset where practical.

Build status should continue to report converted count, skipped count, and package path. The conversion report should include output paths for all generated target files.

## Error Handling

- If a selected preset finds no matching pose files, produce a report with zero conversions and a clear status message.
- Invalid or unreadable `.duf` files remain skipped.
- Unsupported channels are listed as unmapped in the report, not silently guessed.

## Testing

Add unit coverage for:

- Direction preset labels.
- G9 to G8 reverse channel conversion for representative root, hip, thigh, upperarm, forearm, hand, and finger channels.
- G9 path rewriting for Female, Male, Female + Male, and Merged targets.
- G8 Female and Male inputs both landing in Genesis 9.
- `_F` and `_M` suffix handling when G8 Female and Male inputs collide in Genesis 9 output.
- DIM package output containing support metadata for the selected target.
