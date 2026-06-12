# Product Token Registry Design

## Goal

Give packaged products stable product tokens while treating DAZ product identity as `StoreID + ProductToken`. Rebuilding the same source pack should reuse the same visible token. The same product token can be reused for a different output store, but Daz Forge should avoid accidentally assigning the same token to different products inside the same output store.

## User Model

Robert wants Daz Forge to avoid unnecessary new product numbers. If a source pack already contains Smart Content support metadata with a product token, Daz Forge should prefer that token because keeping the original number makes it easier to link the package back to its source.

The important uniqueness boundary is the output store. DAZ can install different products that share a product token as long as their stores are different. That means a DAZ source token such as `83577` can be reused for a private package under `LOCAL USER`, `3D SHARDS`, or another custom store without conflicting with the original DAZ 3D product identity.

If Smart Content is missing or unreadable, Daz Forge should assign and remember a local token. For converted pose products without source tokens, the conversion preset is part of the remembered identity, so each target product can get its own token.

Examples:

- `FN Titan Mk Action Pose for Genesis 9` with source token `112833` defaults to token `112833`.
- A converted private package can also use token `112833` if its output store differs from the original DAZ 3D store.
- A normal DIM Packager rebuild of the same Smart Content source defaults to token `112833`.
- If a source has no Smart Content token, `Genesis 9 -> Genesis 8 Female`, `Genesis 9 -> Genesis 8 Male`, and `Genesis 9 -> Genesis 8 Merged` each receive and remember separate local tokens.

## Registry File

Add a local JSON registry at `config/product-tokens.json`. This file is user-local state like `config/settings.json` and should be ignored by git.

The registry is used for two related jobs:

- remembering generated local tokens and manual overrides
- logging successful `output store ID + product token` assignments so future builds can warn about same-store collisions

Products with readable source Smart Content tokens do not need the registry to choose a token, but successful builds should still be recorded with token source `source`.

The registry stores entries with:

- source store ID
- source product token, when available
- source product name
- output store ID
- workflow label, such as `DIM Packager` or a pose conversion preset label
- generated product name
- assigned local product token
- token source, such as `source`, `generated`, or `manual`
- created timestamp
- updated timestamp

The file should be human-readable JSON so Robert can inspect or repair it if needed.

## Source Identity

When a source zip or folder is selected, Daz Forge derives source identity from the first readable `Runtime/Support/*.dsx` file:

- `StoreID`
- `ProductToken`
- product `VALUE`

If support metadata is missing or unreadable, Daz Forge falls back to a normalized source filename or folder name and an empty source store/token. The fallback should still be stable for the same zip path/name.

The workflow label and output store ID are part of the registry key. For the DIM Packager this label is `DIM Packager`. For the Pose Converter it is the selected conversion preset. This prevents separate target products from accidentally sharing one generated local token inside the same output store, while still allowing the same token to be used by different stores.

## Assignment Flow

When a source and workflow are known:

1. Derive the source identity.
2. Derive the output product name for the current workflow.
3. Derive the current output store ID from the product metadata fields.
4. Look up `source identity + output store + workflow`.
5. If a registry entry exists with token source `manual`, auto-fill the manually saved token.
6. If source Smart Content contains a product token, auto-fill that token.
7. If a registry entry exists without a source token, auto-fill the saved generated token.
8. If no entry exists and there is no source token, auto-fill `settings.next_product_number`.

Before building, Daz Forge should check the registry for existing entries with the same assigned token:

- If the match is the same source/workflow, continue.
- If the match is a different source/workflow in a different output store, continue because that is valid.
- If the match is a different source/workflow in the same output store, warn Robert and require a different token or an explicit manual override.

When building a package:

1. Use the token currently shown in the UI.
2. Upsert the registry entry for `source identity + output store + workflow`.
3. If the token came from source Smart Content and Robert did not change it, save token source `source`.
4. If there was no source token, save token source `generated`.
5. If Robert manually typed a different token, save token source `manual`.
6. If this build used a newly assigned generated token equal to the current `settings.next_product_number`, increment `next_product_number` after saving the registry.
7. Do not blindly advance the counter past unrelated manual numbers.

This keeps source Smart Content as the first choice, the registry as the memory for generated local tokens and overrides, and the settings counter as the source for new local numbers.

## UI Behavior

Keep the token field visible and editable in both the DIM Packager and Pose Converter tabs. Loading a source or changing the conversion preset should refresh the auto-filled token:

- Existing manual override for the same source/workflow/output store: fill the manually saved token.
- Source Smart Content token: fill the source token.
- Existing generated-token registry match for the same output store without source token: fill the remembered local token.
- New source/workflow without source token: fill the next product number.

If Robert edits the token before building, the build uses the edited token and records it for that source/workflow.

No separate registry editor is needed for this version.

## Error Handling

- If the registry file is missing, create it when the first token is saved.
- If the registry JSON is invalid, show a clear error and do not build until it is fixed.
- If settings cannot be saved after a successful registry update, report the settings save error so the next-number counter can be repaired.
- Registry lookup should not block source analysis if support metadata is absent; use the fallback identity.
- A readable source product token should remain valid when reused under a different output store.
- Same-store token reuse for a different source/workflow should produce a clear warning before build.

## Testing

Add unit coverage for:

- Source Smart Content token is reused in the DIM Packager.
- Source Smart Content token is reused in the Pose Converter.
- The same product token is allowed for different output stores.
- The same product token for different source/workflow entries in the same output store warns before build.
- New source/workflow without Smart Content receives `next_product_number`.
- Same source/workflow without Smart Content reuses the saved token.
- Same source with a different pose preset and no Smart Content receives a different token.
- Manual token override is written back to the registry.
- Source-token builds are logged in the registry without changing the chosen token.
- Counter increments only for newly assigned default tokens.
- Missing support metadata falls back to a stable source name.
- Invalid registry JSON produces a clear error.
