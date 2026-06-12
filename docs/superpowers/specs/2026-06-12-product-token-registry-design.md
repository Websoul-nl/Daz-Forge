# Product Token Registry Design

## Goal

Give converted products stable local product tokens. Rebuilding the same source pack with the same conversion preset should reuse the same token, while different conversion presets from the same source should become separate products with separate tokens.

## User Model

Robert wants Daz Forge to remember product-number assignments without needing to manually track them. If a pack is converted again later, Daz Forge should recognize it and fill the same token. If the same source is converted into a different target product, that target gets its own token.

Examples:

- `FN Titan Mk Action Pose for Genesis 9` plus `Genesis 9 -> Genesis 8 Female` gets one token.
- The same source plus `Genesis 9 -> Genesis 8 Male` gets a different token.
- The same source plus `Genesis 9 -> Genesis 8 Merged` gets a third token.

## Registry File

Add a local JSON registry at `config/product-tokens.json`. This file is user-local state like `config/settings.json` and should be ignored by git.

The registry stores entries with:

- source store ID
- source product token
- source product name
- conversion preset label
- generated product name
- assigned local product token
- created timestamp
- updated timestamp

The file should be human-readable JSON so Robert can inspect or repair it if needed.

## Source Identity

When a source zip or folder is selected, Daz Forge derives source identity from the first readable `Runtime/Support/*.dsx` file:

- `StoreID`
- `ProductToken`
- product `VALUE`

If support metadata is missing or unreadable, Daz Forge falls back to a normalized source filename or folder name and an empty source store/token. The fallback should still be stable for the same zip path/name.

The conversion preset is part of the registry key. This prevents separate target products from accidentally sharing one token.

## Assignment Flow

When a pose source and preset are known:

1. Derive the source identity.
2. Derive the converted product name for the selected preset.
3. Look up `source identity + preset`.
4. If an entry exists, auto-fill the saved token.
5. If no entry exists, auto-fill `settings.next_product_number`.

When building a package:

1. Use the token currently shown in the UI.
2. Upsert the registry entry for `source identity + preset`.
3. If the token equals the current `settings.next_product_number`, increment `next_product_number` after saving the registry.
4. If Robert manually typed a different token, save that override in the registry but do not blindly advance the counter past unrelated numbers.

This keeps the settings counter as the source for new numbers, and the registry as the memory for existing source/preset combinations.

## UI Behavior

Keep the token field visible and editable. Loading a source or changing the conversion preset should refresh the auto-filled token:

- Existing registry match: fill the remembered token.
- New source/preset: fill the next product number.

If Robert edits the token before building, the build uses the edited token and records it for that source/preset.

No separate registry editor is needed for this version.

## Error Handling

- If the registry file is missing, create it when the first token is saved.
- If the registry JSON is invalid, show a clear error and do not build until it is fixed.
- If settings cannot be saved after a successful registry update, report the settings save error so the next-number counter can be repaired.
- Registry lookup should not block source analysis if support metadata is absent; use the fallback identity.

## Testing

Add unit coverage for:

- New source/preset receives `next_product_number`.
- Same source/preset reuses the saved token.
- Same source with a different preset receives a different token.
- Manual token override is written back to the registry.
- Counter increments only for newly assigned default tokens.
- Missing support metadata falls back to a stable source name.
- Invalid registry JSON produces a clear error.
