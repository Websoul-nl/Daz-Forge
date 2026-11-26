# Daz Forge User Manual

## What Daz Forge Does

Daz Forge is a Windows desktop tool for preparing DAZ Studio content packages.

Current tools:

- DIM Packager: scan a product folder or ZIP, or gather a product from an installed Runtime/Support DSX, review Smart Content metadata, and build a DIM-style ZIP.
- Pose Converters: convert Genesis 8 Female pose products into Genesis 9 pose products and package the result.
- Optional model suggestions: ask a local LM Studio or Ollama model for metadata suggestions.

The app is intentionally early-stage. Always test a generated DIM package in a clean DAZ library before sharing it.

## Requirements

- Windows.
- Python 3.12 or newer.
- PySide6.
- DAZ Install Manager for installing the generated DIM zips.
- Optional: LM Studio or Ollama if you want model-assisted metadata suggestions.

## First Setup

From the project folder, create a virtual environment if one is not already present:

```powershell
python -m venv .venv
```

Install dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -U pip
```

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
```

If editable install is not available in your environment, install PySide6 and NumPy directly:

```powershell
.\.venv\Scripts\python.exe -m pip install PySide6 numpy
```

## Starting Daz Forge

Use either start script from the project folder:

```powershell
& ".\Start Daz Forge.ps1"
```

or double-click:

```text
Start Daz Forge.bat
```

## Settings And Defaults

Daz Forge creates `config/settings.json` if it does not exist.

Open settings from the cog button in the top-right of the app. Use it to set:

- test library, meaning an optional clean DAZ content library for package validation and test installs
- DIM downloads folder
- package output folder
- staging folder
- default store and DIM prefix
- next product number
- LM Studio and Ollama URLs
- whether staging folders are preserved after builds

Default store is `LOCAL USER`. This is the safest choice for private packages because DAZ Studio can rewrite unknown custom stores to `LOCAL USER` if you edit and save product metadata inside DAZ.

Store catalog entries live in `config/stores.json`. The DIM package prefix and DAZ metadata store are separate concepts:

- DIM zip prefix: short code used in the zip filename.
- Store ID: value written into the support DSX metadata and support filename.

For example, a custom store can use a short DIM prefix but a longer Store ID.
Artist-specific store codes belong on the product metadata fields for the package you are building, not in global settings.

### Product Tokens

Daz Forge treats product identity as the combination of Store ID and Product token. The same product token can be reused under a different store.

When source Smart Content contains a product token, Daz Forge reuses that token by default. If no source token is available, Daz Forge assigns `next_product_number`, remembers the assignment in `config/product-tokens.json`, and increments the next number after a successful build.

`config/product-tokens.json` is local machine state and is ignored by git, like `config/settings.json`.

## DIM Packager Workflow

1. Open the `DIM Packager` tab.
2. Select a product folder or zip.
3. Daz Forge scans user-facing files such as `.duf`, `.dsa`, `.dse`, and uncommon user-facing `.dsf` files.
4. Review the grid:
   - Content Type
   - Category
   - Compatibility Base
   - Compatibilities
   - Warnings
5. Edit fields directly in the grid where needed.
6. Set product metadata in the inspector:
   - Product name
   - Store
   - Prefix/code
   - Token
   - GUID
   - Artists
   - Product image
7. Click `Build Package`.
8. Install the generated zip with DAZ Install Manager.

Generated packages include:

- `Manifest.dsx`
- `Supplement.dsx`
- `Content/Runtime/Support/*.dsx`
- `Content/Runtime/Support/*.dsa`
- product image when selected
- product content files

Existing support files in the source are skipped and replaced with the newly generated support files.

## Gathering an Installed Product from DSX

Use this workflow when you only have a product's installed DAZ library and
want a redistributable **personal backup**/DIM-style package of its own files.

1. Open **DIM Packager** and drop a `Runtime/Support/*.dsx` file into the
   window, paste its path, or use **Browse File**.
2. The **Analyze** button changes to **Gather**. Click **Gather**.
3. Daz Forge reads `Assets` and `SupportAssets` from the DSX, resolves
   references in DSON DUF/DSF files (also gzip-compressed), and looks for
   referenced product-specific textures, morphs, and thumbnails.
4. Open the **Gathered Files** tab. Each path is classified:
   - **included:** the DSX declares it, or it is referenced in the product's
     own namespace without a conflicting other-product declaration;
   - **base:** protected DAZ Genesis base assets (excluded even if the DSX
     lists them);
   - **external:** another installed product claims ownership (excluded);
   - **unknown:** no reliable ownership evidence (excluded by default);
   - **missing:** file referenced but absent. Missing explicitly declared
     product files block packaging.
5. Review **Warnings**, especially inferred ownership, unknown references
   and script dependencies. Complete the usual Product and Selected File
   review and click **Build Package**.

The gathered-file review remains in the application; no extra JSON report is written next to the ZIP. The ZIP retains normal relative `Content/...` paths.

**Important limitations:** Static dependency traversal cannot execute DAZ
scripts or prove ownership from references alone. `SupportAssets` is often
more complete than `Assets`, but even a valid DSX may be incomplete. A
conservative built-in Genesis-base exclusion rule protects common base assets
without excluding all vendor morphs under `data/DAZ 3D`. A clean-library
installation test is still required; do not assume a warning-free gather means
the product is independent of other DAZ products.

The original product's ownership and redistribution rights are unchanged by
creating a DIM ZIP. Do not redistribute copyrighted files without permission.

## Product Images

Product images should be portrait-oriented. DAZ accepts many sizes, but a 3:4-ish image such as `570 x 740` generally looks better than the tiny default size.

If the source has a support image, Daz Forge can reuse it. Otherwise choose an image in the Product Image tab.

## Pose Converter Workflow

1. Open the `Pose Converters` tab.
2. Choose a conversion preset:
   - `Genesis 8 -> Genesis 9`
   - `Genesis 9 -> Genesis 8 Female`
   - `Genesis 9 -> Genesis 8 Male`
   - `Genesis 9 -> Genesis 8 Female + Male`
   - `Genesis 9 -> Genesis 8 Merged`
3. Select a pose product zip, unpacked folder, or installed product DSX. You can drag a source onto the `Pose Converters` tab while that tab is open.
4. Choose an output folder.
5. Check product metadata:
   - Product name
   - Store
   - Token
   - GUID
6. Click `Build Converted DIM Package`.

The converter:

- Finds pose `.duf` files under the selected source figure folders.
- Converts mapped Genesis 8 and Genesis 9 pose bone channels in the selected direction.
- Copies artists from the original support metadata when available.
- Preserves character/root translations and rotations.
- Copies matching `.duf.png` and `.tip.png` thumbnails.
- Builds a new DIM zip for the converted pose product.

For `Genesis 8 -> Genesis 9`, Genesis 8 Female and Genesis 8 Male source poses both land under `People/Genesis 9/Poses`. If matching Female and Male inputs would create the same output file, Daz Forge adds `_F` and `_M` suffixes.

For an installed product, select its DSX inside the library's `Runtime/Support` folder. The converter gathers that product's files, preserves its artists, product image and matching pose thumbnails, and creates a new converted DIM ZIP without changing the installed originals. Missing declared files or no poses matching the selected conversion direction block the build.

For Genesis 9 to Genesis 8, choose whether to create Female, Male, both separate target folders, or a merged `People/Genesis 8/Poses` output.

The converter is not a perfect substitute for a DAZ-authored converter. Test a few poses visually in DAZ Studio.

## Character Conversion

1. Drop an installed product DSX from its library's `Runtime/Support` folder
   onto **Character Conversion**, or browse to it. Forge finds the full-skin
   DUFs listed in the product. Choose one when there is more than one. Only
   the product's listed material variants are considered; missing presets
   and other full skins appear in the report.
2. To convert a loose full-skin DUF instead, drop or browse to it and
   optionally select its variant folder. A preset may not declare its UVs;
   confirm the source UV only when known.
3. Enter the character name, select the library containing Genesis 9 Starter
   Essentials, and choose an export folder outside your DAZ libraries. Click
   **Export Materials**.

Iray Uber is the primary export for an Uber source. Check **Also export
PBRSkin** for a second, approximate shader conversion. A PBRSkin source
offers PBRSkin only. Apply one full-skin preset at a time. The export
contains a private ZIP, the unpacked content, and `Review.json`. The
tab shows the review items as well. Exporting does not install content,
alter a DAZ scene, or overwrite an earlier export.

The standard UV routes cover G8 Base Female and Base Male and G8.1 Female
and Male on both legacy and native Base UVs. These are separate conversions,
not a combined skin texture. Forge uses the matching bundle automatically.
If it is missing, **UV transfer override** accepts the collection root or an
individual conversion folder. Older collections using root-level
`<generation> <UV>.json` manifests still work. Forge does not guess another UV.

Each conversion under `forge/material_converter/uv_transfers/` has a
`manifest.json` with local atlas paths. Files use `<part>_uv.npz` for lookups
and `<part>_tangent.npz` for optional Iray Uber source-normal calibration.
The G8.1 folder names distinguish `legacy` from `native`. See the
[UV bundle notes](../forge/material_converter/uv_transfers/README.md)
before packaging or distributing the data.

Forge preserves supported skin settings, uses native G9 detail for
PBRSkin, and retains source tangent normals for Uber only where a
verified calibration is available. It can output native LIE color
stacks and compatible eye, mouth, lash and tear material presets when
their transfers are present. Shape transfer, grafts, geometry shells
and other unsupported variants are not automatically converted; the
report lists affected inputs. Fix or compare flagged joins and settings
in DAZ before treating the conversion as final. There is no tuning panel
in this release.

Remapped textures use source-sized square outputs, up to 4096 pixels per side.
For example, a 2K color map stays 2K even if its normal map is 4K. When several
source maps contribute to one output, Forge uses the largest source so it
does not lose detail. A layered image uses the largest of its base and paint
layers for its shared canvas. Forge samples the source textures at the chosen
size; it does not enlarge a previously baked texture. `Review.json` lists the
exported map sizes.

## Optional Local AI

Daz Forge can ask a local model for metadata suggestions. This is optional.

The Windows app selects LM Studio at `http://127.0.0.1:1234/v1`. Enable its local server and use the installed model key `qwen3-4b`. The app loads the selected model explicitly and verifies its identity before accepting suggestions. Off disables model suggestions. An installed Ollama CLI no longer changes the default. The legacy Ollama adapter remains available to explicit integrations.

Model suggestions are shown as suggestions. You choose which ones to apply.

## DAZ Store Caveat

DIM can install metadata for custom stores, but DAZ Studio's Content DB Editor may not be able to resolve a custom store that is not registered in the local DAZ database. If you open and save such a product in DAZ, DAZ may rewrite the product to `LOCAL USER`.

For private packages, `LOCAL USER` is the safest store.

## Troubleshooting

If the app will not start:

- Confirm `.venv\Scripts\python.exe` exists.
- Reinstall dependencies.
- Start from PowerShell so you can read any error messages.

If a DIM package installs but the product image is missing:

- Confirm the package contains `Content/Runtime/Support/<support-name>.jpg` or `.png`.
- Confirm the support DSX contains a `SupportAssets` block.
- Rebuild the package after selecting a product image.

If DAZ shows the wrong store:

- Use `LOCAL USER`, or make sure that exact custom Store ID already exists in DAZ.
- Do not edit and save unknown-store products in DAZ unless you expect DAZ to rewrite the store.

If converted poses are offset incorrectly:

- Test whether the original pose used figure/root transforms or hip transforms.
- Rebuild with the latest Daz Forge version.
- Validate a few poses manually in DAZ Studio.
