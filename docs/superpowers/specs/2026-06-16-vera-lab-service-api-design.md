# Vera Lab Service API Design

Date: 2026-06-16
Status: Approved direction, pending implementation plan
Supersedes: `2026-06-15-daz-forge-companion-services-design.md`

## Purpose

Keep Vera's Lab as a separate local service shelf for now, while making it
portable and API-driven enough for Daz Forge, Wayfinder, and future AI skills to
call it cleanly.

The revised direction is not to move Daz-specific workers into Daz Forge yet.
Instead, Daz Forge should consume Vera Lab services through stable local API
endpoints. Vera's Lab should become less dependent on the literal
`D:\AI\06_local-ai` path so the folder can be moved later without breaking all
services.

## Ownership Boundary

Vera's Lab owns local AI service infrastructure:

- service supervision
- worker lifecycle
- local service APIs
- image and document workers
- Daz asset scout service
- shared local AI runtime checks
- service logs, caches, indexes, and generated outputs

Daz Forge owns the Daz desktop product:

- DIM package building
- Smart Content metadata review
- pose conversion
- user-facing Daz workflows
- optional calls into Vera Lab services

Wayfinder will later own discovery and routing:

- find available local capabilities
- decide which service should handle a request
- call Vera Lab or Daz Forge APIs through stable contracts
- avoid duplicating Daz or local AI domain logic

The working rule:

> Vera's Lab serves capabilities. Daz Forge uses them. Wayfinder routes to them.

## Active Architecture

Vera's Lab remains the local service shelf:

```text
<veraLabRoot>
  config
  data
  logs
  models
  outputs
  platform
  tools
  workers
  workflows
```

Daz Forge keeps its own product code and calls the Lab when useful:

```text
daz-forge
  forge
  config
  docs
  tests
```

The connection between them should be API-based:

```text
Daz Forge UI or Python code
  -> Vera Lab service endpoint
  -> worker-specific API
  -> JSON result with evidence and safe path behavior
```

## Portability Goal

The main cleanup target is path independence. Vera's Lab should be movable by
changing one local root setting and rerunning a setup or validation command.

The target test:

```text
Can Vera's Lab be moved or renamed, then restored by changing one root config
and running one validation command?
```

If the answer is no, the next cleanup target is a hardcoded path, service
registration assumption, or runtime dependency.

## Configuration Design

Introduce a single lab root concept:

```text
veraLabRoot = <current Vera Lab folder>
```

All service paths should resolve from that root unless they point to external
machine resources.

Examples:

```text
${veraLabRoot}\workers
${veraLabRoot}\platform
${veraLabRoot}\data
${veraLabRoot}\logs
${veraLabRoot}\models
${veraLabRoot}\outputs
```

External machine resources remain explicit:

- Daz Install Manager manifest directory
- Daz content library roots
- Python runtime path when not bundled
- Node runtime path when not bundled
- LM Studio or Ollama endpoint URLs
- ComfyUI install or user-data locations

The supervisor defaults may keep symbolic variables such as `${veraLabRoot}` and
`${aiRoot}`, but machine-local files should be the only place that knows the
current absolute install location.

## API Surface

The first stable consumer-facing API should focus on existing services.

Daz asset scout:

```text
GET  /api/health
POST /api/workers/daz-asset-scout/search
POST /api/workers/daz-asset-scout/assets/search
POST /api/workers/daz-asset-scout/refresh-index
GET  /api/workers/daz-asset-scout/file
```

Future AI or Wayfinder skill operations can wrap those endpoints:

```text
search_daz_assets(query, generation, kind, semantic_tags)
get_daz_asset_recipe(asset_id)
refresh_daz_index()
```

Script drafting should remain a later capability:

```text
draft_daz_script(recipe)
```

The first script-drafting version should generate a readable `.dsa` draft only.
It should not execute scripts in Daz Studio.

## Daz Forge Integration

Daz Forge should treat Vera Lab as optional.

When the Lab is available, Forge may:

- health-check the relevant endpoint
- search installed Daz products
- ask for normalized asset results
- copy or consume outfit recipe JSON
- show preview or match evidence returned by the service

When the Lab is unavailable, Forge should still:

- start normally
- build DIM packages
- convert poses
- edit Smart Content metadata
- call direct LM Studio or Ollama metadata suggestions if configured

Daz Forge should not take ownership of Vera Lab service code in this design.

## Future Skill Shape

A future skill should make the Lab easy for agents to use from either Wayfinder
or Forge-adjacent workflows.

The skill should:

- discover the Lab endpoint from config
- health-check before calls
- expose compact operations instead of raw endpoint details
- return evidence-attached summaries
- hide raw local paths by default
- allow trusted local automation mode when full paths are required

The skill should not become a second implementation of Daz search or recipe
logic. It should be a caller, not an owner.

## Migration Phases

Phase 1: Document revised ownership.

- Mark the Daz Forge companion-service migration spec as superseded.
- Add this active service-API design.
- Avoid moving service code.

Phase 2: Make Vera Lab root-aware.

- Add or formalize `veraLabRoot`.
- Replace hardcoded `D:\AI\06_local-ai` references in service config with
  root-relative variables where practical.
- Keep external machine resources explicit.

Phase 3: Add validation.

- Add a command or script that checks resolved paths, ports, service files, and
  key external dependencies.
- Report which values still bind the Lab to the old path.

Phase 4: Let Daz Forge consume services by API.

- Add a configurable Lab endpoint in Daz Forge settings.
- Add health-check behavior.
- Keep Daz Forge workflows functional without the Lab.

Phase 5: Prepare Wayfinder and skill access.

- Document the AI-facing contract.
- Add a thin skill or adapter that calls Vera Lab endpoints.
- Let Wayfinder discover and route to the Lab rather than absorbing it.

## Error Handling

Vera Lab services should report:

- missing lab root
- unresolved root-relative path
- missing external Daz manifest directory
- missing Daz library root
- unavailable worker dependency
- unavailable local model endpoint
- blocked path access outside allowed roots
- stale or missing cache/index

Daz Forge should display unavailable Lab services as optional degraded
capabilities, not app-breaking errors.

## Testing

Initial verification should cover:

- resolved config paths after changing `veraLabRoot`
- supervisor health
- Daz asset scout health
- Daz asset search against a known local manifest set
- blocked file access outside allowed Daz roots
- Daz Forge startup when Vera Lab is offline
- Daz Forge health-check behavior when Vera Lab is online

Migration verification should include a practical move rehearsal:

1. Copy or rename the Lab folder to a test path.
2. Update only the lab root config.
3. Run validation.
4. Start the supervisor.
5. Confirm key endpoints respond.

## Non-Goals

This design does not:

- move `daz-asset-scout` into Daz Forge
- merge Vera Lab and Daz Forge
- make Wayfinder responsible for Daz domain logic
- execute generated Daz scripts automatically
- solve every `D:\AI` cleanup decision at once
- require Daz Forge to depend on Vera Lab for core package or pose workflows

## Implementation Bias

Favor portability and stable API contracts over rewrites.

The current services already work. The weak point is path binding and ownership
clarity, not the idea of a separate Lab service shelf.
