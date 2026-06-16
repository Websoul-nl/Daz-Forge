# Daz Forge Companion Services Design

Date: 2026-06-15
Status: Superseded on 2026-06-16
Superseded by: `2026-06-16-vera-lab-service-api-design.md`

## Supersession Note

This design captured an earlier option where Daz-specific services would move
into the Daz Forge repository as companion services. Robert revised the
ownership decision on 2026-06-16: Vera's Lab should remain a separate service
shelf for now, while becoming portable and API-driven enough for Daz Forge,
Wayfinder, and future AI skills to consume it.

Keep this document as historical thinking. Do not use it as the implementation
plan.

## Purpose

Move Daz-specific local AI service work out of the general `D:\AI\06_local-ai`
shelf and into Daz Forge as companion services. The local-ai shelf will be
dismantled gradually, with each part migrated to the project that actually owns
its domain.

Daz Forge should own Daz semantics: installed Daz library search, DIM manifest
indexing, Smart Content metadata assistance, outfit recipes, and future Daz
script drafting. Wayfinder can later discover and route to these capabilities,
but it should not own the Daz-specific logic.

## Current Context

Daz Forge is a Windows desktop tool for:

- DIM package building.
- Smart Content metadata review.
- Genesis pose conversion.
- Optional metadata suggestions through local LM Studio or Ollama providers.

`D:\AI\06_local-ai` currently contains Vera's local AI platform shelf,
including a `daz-asset-scout` worker. That worker already provides:

- DIM manifest inventory.
- Daz library root remapping through `library-roots.json`.
- SQLite-backed search.
- Lazy Runtime/Support enrichment.
- Optional thumbnail analysis through `image-worker`.
- Outfit recipe JSON for clothing results.
- An asset-awareness response shape for callers such as NeoStack or Wayfinder.

The overlap is real, but the ownership is uneven. Daz Forge is the natural home
for Daz domain behavior. The local-ai shelf should not remain the long-term home
for Daz-specific service code.

## Recommended Ownership

Daz Forge should own companion services that are tightly coupled to Daz content.

Wayfinder should later consume these services through a stable API or skill
adapter. Vera's broader local AI infrastructure can still help with model
endpoints, runtime checks, and machine-level setup, but Daz-specific indexing and
recipes belong with Forge.

The working rule:

> Daz Forge owns Daz semantics. Wayfinder routes to them. Vera verifies the local
> machine room works.

## Proposed Repository Shape

Add a service area to Daz Forge:

```text
daz-forge
  forge
  services
    daz-asset-scout
    daz-script-smith
  config
    services.example.json
    services.local.json
  docs
    ai-skill-contract.md
```

`forge` remains the desktop application.

`services/daz-asset-scout` becomes the migrated companion service for installed
Daz library search and outfit recipes.

`services/daz-script-smith` is reserved for a later recipe-to-`.dsa` draft
generator. The first version should generate scripts only; it should not execute
them inside Daz Studio.

`config/services.example.json` documents expected service configuration.

`config/services.local.json` is machine-local and ignored by git. It should hold
absolute paths such as Daz manifest locations, active Daz library roots, Python
runtime paths, Node runtime paths, cache paths, and ports.

`docs/ai-skill-contract.md` documents the future AI-facing contract.

## Capability Boundaries

Daz Forge desktop app:

- Builds DIM-style packages.
- Converts pose products.
- Reviews and edits Smart Content metadata.
- Calls local model providers for metadata suggestions.
- May start, stop, or health-check companion services.
- May consume companion service results in the UI.

`daz-asset-scout` companion service:

- Indexes installed DIM products.
- Resolves Daz library roots using configurable root maps.
- Searches products and assets.
- Enriches returned products from Runtime/Support metadata.
- Optionally requests visual enrichment from an image worker.
- Returns outfit recipe JSON when a stable recipe can be built.
- Serves preview images only from allowed Daz library roots.

Future `daz-script-smith` companion service:

- Reads one reviewed outfit recipe or action contract.
- Generates a readable `.dsa` draft.
- Includes comments and safety notes in generated scripts.
- Does not execute generated scripts.

Wayfinder:

- Discovers Daz Forge capabilities.
- Routes user or agent requests to the right service.
- Does not duplicate Daz metadata, recipe, or script-generation logic.

Future AI skill:

- Provides a thin, stable interface for agents.
- Calls Daz Forge companion services.
- Returns compact, evidence-attached answers.
- Avoids exposing raw local paths unless the caller explicitly requests trusted
  local automation mode.

## Stable Skill Contract

The future skill should expose these operations:

```text
search_daz_assets(query, generation, kind, semantic_tags)
get_daz_asset_recipe(asset_id)
refresh_daz_index()
draft_daz_script(recipe)
```

The first implementation can map these operations to HTTP endpoints.

The contract should preserve these principles:

- Search results include match reasons and evidence.
- Recipe results are explicit JSON action contracts.
- Path-bearing fields are hidden by default.
- Trusted local automation may opt into full local paths.
- Script drafting is separate from script execution.

## Configuration Design

Companion services should not contain hardcoded `D:\AI\06_local-ai` paths after
migration.

Configuration should support:

- Repo-relative defaults for cache, output, and service folders.
- Machine-local absolute paths for Daz Install Manager manifests.
- Machine-local absolute paths for Daz content libraries.
- Machine-local runtime paths when a bundled runtime is not used.
- Port configuration.
- Optional pointers to external local AI services such as image workers.

The first migration can keep the existing `daz-asset-scout` JSON shape, but it
must move machine-specific values into `config/services.local.json` or a
service-local ignored config.

## Data Flow

Library search:

1. Daz Forge or an AI caller sends a query to `daz-asset-scout`.
2. The service loads or refreshes the DIM manifest index.
3. SQLite FTS narrows candidates when available.
4. The JS scorer ranks and enriches results.
5. Runtime/Support metadata is parsed lazily for returned candidates.
6. Optional visual enrichment is requested only for a small result subset.
7. Results return with match evidence, semantic tags, preview references, and
   recipe availability.

Recipe use:

1. Caller selects a result with an outfit recipe.
2. Caller requests the recipe or receives it inline in trusted mode.
3. Future `daz-script-smith` turns the reviewed recipe into a `.dsa` draft.
4. Robert reviews the draft before any Daz Studio execution is considered.

## Migration Phases

Phase 1: Document and freeze the contract.

- Add this design spec.
- Add an implementation plan before moving files.
- Avoid changing current Daz Forge behavior.

Phase 2: Move `daz-asset-scout` into Daz Forge.

- Copy the existing worker into `services/daz-asset-scout`.
- Preserve the current HTTP API paths initially.
- Replace absolute `D:\AI\06_local-ai` paths with config-driven paths.
- Add service-local README and startup scripts.
- Keep generated caches, logs, and SQLite data ignored by git.

Phase 3: Wire Daz Forge to the companion service.

- Add settings for service URL and enablement.
- Add health-check behavior.
- Add an optional UI entry point for installed library search.
- Keep package building and pose conversion functional without the service.

Phase 4: Prepare Wayfinder and skill access.

- Write `docs/ai-skill-contract.md`.
- Add a small command-line or HTTP adapter that agents can call predictably.
- Let Wayfinder discover the service rather than reimplementing it.

Phase 5: Migrate or retire old local-ai pieces.

- Confirm Daz Forge service parity.
- Update old Vera supervisor config to remove or disable the Daz worker.
- Leave a short migration note in `D:\AI\06_local-ai` while the broader folder is
  being dismantled.

## Error Handling

The companion service should report:

- Missing Daz manifest directory.
- Missing or stale library root maps.
- SQLite cache unavailable, with fallback search when possible.
- Image worker unavailable, without failing plain search.
- Blocked preview file requests outside allowed Daz roots.
- Invalid recipe requests.
- Local model provider unavailable.

Daz Forge should treat the companion service as optional. If the service is not
running, core packaging and pose conversion still work.

## Testing

Initial tests should cover:

- Config path resolution without `D:\AI\06_local-ai`.
- Search endpoint health and basic query response.
- Library root remapping.
- Blocked file serving outside allowed roots.
- Recipe shape stability.
- Daz Forge behavior when the companion service is unavailable.

Migration verification should include:

- `node --check` for migrated JavaScript services.
- Python tests for Daz Forge.
- A smoke search against a known local Daz manifest set.
- A dry run of recipe-to-script drafting once `daz-script-smith` exists.

## Non-Goals

This migration does not:

- Merge all of `D:\AI\06_local-ai` into Daz Forge.
- Make Wayfinder responsible for Daz-specific logic.
- Execute generated Daz scripts automatically.
- Require the Daz Forge desktop app to depend on the service for core package
  building or pose conversion.
- Solve the final architecture of every local-ai service.

## Open Follow-Up

The implementation plan should decide whether the migrated service keeps Node.js
as its runtime long-term or is gradually rewritten behind the same HTTP contract.
The first migration should favor parity and portability over a rewrite.
