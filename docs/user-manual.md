# Daz Forge User Manual

## What Daz Forge Does

Daz Forge is a Windows desktop tool for preparing DAZ Studio content packages.

Current tools:

- DIM Packager: scan a product folder or zip, review Smart Content metadata, and build a DIM-style zip.
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

If editable install is not available in your environment, install PySide6 directly:

```powershell
.\.venv\Scripts\python.exe -m pip install PySide6
```

## Starting Daz Forge

Use either start script from the project folder:

```powershell
.\Start Daz Forge.ps1
```

or double-click:

```text
Start Daz Forge.bat
```

## Settings And Defaults

Daz Forge creates `config/settings.json` if it does not exist.

Default store is `LOCAL USER`. This is the safest choice for private packages because DAZ Studio can rewrite unknown custom stores to `LOCAL USER` if you edit and save product metadata inside DAZ.

Store catalog entries live in `config/stores.json`. The DIM package prefix and DAZ metadata store are separate concepts:

- DIM zip prefix: short code used in the zip filename.
- Store ID: value written into the support DSX metadata and support filename.

For example, a custom store can use a short DIM prefix but a longer Store ID.

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

## Product Images

Product images should be portrait-oriented. DAZ accepts many sizes, but a 3:4-ish image such as `570 x 740` generally looks better than the tiny default size.

If the source has a support image, Daz Forge can reuse it. Otherwise choose an image in the Product Image tab.

## Pose Converter Workflow

1. Open the `Pose Converters` tab.
2. Select a Genesis 8 Female pose product zip or unpacked folder.
3. Choose an output folder.
4. Check product metadata:
   - Product name
   - Store
   - Token
   - GUID
   - Artists
5. Click `Build Converted DIM Package`.

The converter:

- Finds pose `.duf` files under Genesis 8 Female pose folders.
- Converts mapped Genesis 8 Female bone channels to Genesis 9 bone channels.
- Preserves character/root translations and rotations.
- Copies matching `.duf.png` and `.tip.png` thumbnails.
- Builds a new DIM zip for the converted Genesis 9 pose product.

The converter is not a perfect substitute for a DAZ-authored converter. Test a few poses visually in DAZ Studio.

## Optional Local AI

Daz Forge can ask a local model for metadata suggestions. This is optional.

Supported providers:

- Ollama, default URL `http://127.0.0.1:11434`
- LM Studio, default URL `http://127.0.0.1:1234/v1`

Suggested small model:

```powershell
ollama pull qwen3:4b
```

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
