# Product Token Registry Design

## Goal

Give packaged products stable product tokens while reusing source Smart Content tokens when they already exist. Rebuilding the same source pack should reuse the same visible token. New local tokens are only generated when source Smart Content does not provide a usable product token.

## User Model

Robert wants Daz Forge to avoid unnecessary new product numbers. If a source pack already contains Smart Content support metadata with a product token, Daz Forge should reuse that token because DAZ allows products with the same name but different product numbers, and keeping the original token makes it easier to link the package back to its source.

If Smart Content is missing or unreadable, Daz Forge should assign and remember a local token. For converted pose products without source tokens, the conversion preset is part of the remembered identity, so each target product can get its own token.

Examples:

- `FN Titan Mk Action Pose for Genesis 9` with source token `112833` defaults to token `112833`.
- A normal DIM Packager rebuild of the same Smart Content source also defaults to token `112833`.
- If a source has no Smart Content token, `Genesis 9 -> Genesis 8 Female`, `Genesis 9 -> Genesis 8 Male`, and `Genesis 9 -> Genesis 8 Merged` each receive and remember separate local tokens.

## Registry File

Add a local JSON registry at `config/product-tokens.json`. This file is user-local state like `config/settings.json` and should be ignored by git.

The registry is only needed for generated local tokens and manual overrides. Products with readable source Smart Content tokens do not need registry entries unless Robert manually changes the token before building.

The registry stores entries with:

- source store ID
- source product token, when available
- source product name
- workflow label, such as `DIM Packager` or a pose conversion preset label
- generated product name
- assigned local product token
- token source, such as `source`, `registry`, `generated`, or `manual`
- created timestamp
- updated timestamp

The file should be human-readable JSON so Robert can inspect or repair it if needed.

## Source Identity

When a source zip or folder is selected, Daz Forge derives source identity from the first readable `Runtime/Support/*.dsx` file:

- `StoreID`
- `ProductToken`
- product `VALUE`

If support metadata is missing or unreadable, Daz Forge falls back to a normalized source filename or folder name and an empty source store/token. The fallback should still be stable for the same zip path/name.

The workflow label is part of the registry key. For the DIM Packager this label is `DIM Packager`. For the Pose Converter it is the selected conversion preset. This prevents separate target products from accidentally sharing one generated local token.

## Assignment Flow

When a source and workflow are known:

1. Derive the source identity.
2. Derive the output product name for the current workflow.
3. If source Smart Content contains a product token, auto-fill that token.
4. If no source token exists, look up `source identity + workflow`.
5. If a registry entry exists, auto-fill the saved token.
6. If no entry exists, auto-fill `settings.next_product_number`.

When building a package:

1. Use the token currently shown in the UI.
2. If the token came from source Smart Content and Robert did not change it, no registry entry is required.
3. If there was no source token, upsert the registry entry for `source identity + workflow`.
4. If Robert manually typed a different token, save that override in the registry for the current source/workflow.
5. If the token equals the current `settings.next_product_number`, increment `next_product_number` after saving the registry.
6. Do not blindly advance the counter past unrelated manual numbers.

This keeps source Smart Content as the first choice, the registry as the memory for generated local tokens and overrides, and the settings counter as the source for new local numbers.

## UI Behavior

Keep the token field visible and editable in both the DIM Packager and Pose Converter tabs. Loading a source or changing the conversion preset should refresh the auto-filled token:

- Source Smart Content token: fill the source token.
- Existing registry match without source token: fill the remembered local token.
- New source/workflow without source token: fill the next product number.

If Robert edits the token before building, the build uses the edited token and records it for that source/workflow.

No separate registry editor is needed for this version.

## Error Handling

- If the registry file is missing, create it when the first token is saved.
- If the registry JSON is invalid, show a clear error and do not build until it is fixed.
- If settings cannot be saved after a successful registry update, report the settings save error so the next-number counter can be repaired.
- Registry lookup should not block source analysis if support metadata is absent; use the fallback identity.
- A readable source product token should remain valid even if the source product name matches another local product name.

## Testing

Add unit coverage for:

- Source Smart Content token is reused in the DIM Packager.
- Source Smart Content token is reused in the Pose Converter.
- New source/workflow without Smart Content receives `next_product_number`.
- Same source/workflow without Smart Content reuses the saved token.
- Same source with a different pose preset and no Smart Content receives a different token.
- Manual token override is written back to the registry.
- Counter increments only for newly assigned default tokens.
- Missing support metadata falls back to a stable source name.
- Invalid registry JSON produces a clear error.
