# Bidirectional Pose Converter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pose conversion presets for Genesis 8 to Genesis 9 and Genesis 9 to Genesis 8 Female, Male, Both, and Merged outputs.

**Architecture:** Introduce conversion preset objects that own source matching, target path rewriting, product naming, and channel rules. Keep low-level DUF channel conversion in `forge/pose_converter/converter.py`, and keep product folder/package orchestration in `forge/pose_converter/product.py`. Add one UI dropdown in the existing Pose Converters page and pass the selected preset into the package builder.

**Tech Stack:** Python 3.12, PySide6, pytest, existing Daz Forge pose converter modules.

---

### Task 1: Conversion Presets And Reverse Channel Rules

**Files:**
- Modify: `forge/pose_converter/mapping.py`
- Modify: `forge/pose_converter/converter.py`
- Test: `tests/test_pose_converter.py`

- [ ] **Step 1: Write failing tests**

Add tests that import `PoseConversionPreset`, `convert_pose`, and verify:

```python
def test_conversion_preset_labels_are_stable() -> None:
    labels = [preset.label for preset in PoseConversionPreset]
    assert labels == [
        "Genesis 8 -> Genesis 9",
        "Genesis 9 -> Genesis 8 Female",
        "Genesis 9 -> Genesis 8 Male",
        "Genesis 9 -> Genesis 8 Female + Male",
        "Genesis 9 -> Genesis 8 Merged",
    ]
```

```python
def test_convert_g9_pose_to_g8_inverts_representative_channels() -> None:
    pose = {
        "asset_info": {"id": "/People/Genesis%209/Poses/Carry/Pose.duf", "type": "preset_pose"},
        "scene": {
            "animations": [
                {"url": "name://@selection:?translation/x/value", "keys": [[0, 11]]},
                {"url": "name://@selection/hip:?translation/y/value", "keys": [[0, -4]]},
                {"url": "name://@selection/l_thigh:?rotation/z/value", "keys": [[0, 16]]},
                {"url": "name://@selection/l_upperarm:?rotation/x/value", "keys": [[0, 25]]},
                {"url": "name://@selection/l_forearm:?rotation/y/value", "keys": [[0, 30]]},
                {"url": "name://@selection/l_index1:?rotation/x/value", "keys": [[0, 5]]},
            ]
        },
    }
    result = convert_pose(pose, PoseConversionPreset.G9_TO_G8_FEMALE)
    converted = _meaningful_animation_map(result.pose)
    assert converted[("", "translation", "x")] == 11
    assert converted[("hip", "translation", "y")] == -4
    assert converted[("lThighBend", "rotation", "z")] == 10
    assert converted[("lShldrBend", "rotation", "x")] == 25
    assert converted[("lForearmBend", "rotation", "y")] == 30
    assert converted[("lIndex1", "rotation", "x")] == 5
```

- [ ] **Step 2: Run red tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp .codex-local\pytest-tmp tests\test_pose_converter.py::test_conversion_preset_labels_are_stable tests\test_pose_converter.py::test_convert_g9_pose_to_g8_inverts_representative_channels -q
```

Expected: fail because preset and generic `convert_pose` API do not exist.

- [ ] **Step 3: Implement mapping and converter APIs**

Add `PoseConversionPreset` and reverse mapping rule tables. Add `convert_pose(pose, preset)` and keep `convert_g8f_pose_to_g9()` as a compatibility wrapper.

- [ ] **Step 4: Run green tests**

Run the same focused command. Expected: both tests pass.

### Task 2: Product Path Rewriting And Multi-Output Modes

**Files:**
- Modify: `forge/pose_converter/product.py`
- Test: `tests/test_pose_converter.py`

- [ ] **Step 1: Write failing tests**

Add tests for:

```python
def test_convert_g9_product_writes_female_male_and_merged_targets(tmp_path: Path) -> None:
    ...
```

and:

```python
def test_convert_g8_male_and_female_inputs_land_in_g9_with_collision_suffixes(tmp_path: Path) -> None:
    ...
```

Use tiny synthetic DUF files and thumbnails written by existing `save_duf`/`write_file` helpers.

- [ ] **Step 2: Run red tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp .codex-local\pytest-tmp tests\test_pose_converter.py::test_convert_g9_product_writes_female_male_and_merged_targets tests\test_pose_converter.py::test_convert_g8_male_and_female_inputs_land_in_g9_with_collision_suffixes -q
```

Expected: fail because `convert_pose_product()` has no preset argument and only scans G8F source paths.

- [ ] **Step 3: Implement product conversion modes**

Change `convert_pose_product(source, output_dir, preset=PoseConversionPreset.G8_TO_G9)` so it uses preset source matchers and target path builders. Preserve thumbnails, reports, support image copy, and output report structure.

- [ ] **Step 4: Run green tests**

Run the focused command again. Expected: both tests pass.

### Task 3: DIM Package And UI Wiring

**Files:**
- Modify: `forge/pose_converter/product.py`
- Modify: `forge/ui/main_window.py`
- Modify: `forge/ui/pages/pose_converter_page.py`
- Modify: `docs/user-manual.md`
- Test: `tests/test_pose_converter.py`
- Test: `tests/test_ui_review.py`

- [ ] **Step 1: Write failing tests**

Add tests that:

```python
def test_pose_converter_page_has_conversion_preset_dropdown(qapp) -> None:
    window = MainWindow(available_model_providers=())
    assert [window.pose_preset_combo.itemText(index) for index in range(window.pose_preset_combo.count())] == [...]
```

and update the fake builder test to assert `preset` is passed to `pose_package_builder`.

- [ ] **Step 2: Run red tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp .codex-local\pytest-tmp tests\test_ui_review.py::test_pose_converter_page_has_conversion_preset_dropdown tests\test_ui_review.py::test_pose_converter_tab_builds_converted_dim_package -q
```

Expected: fail because the dropdown and builder preset argument do not exist.

- [ ] **Step 3: Implement UI wiring**

Add `pose_preset_combo` to `MainWindow`, place it in `PoseConverterPage`, and pass the selected preset to `build_converted_pose_dim_package()`. Update placeholders and generated product names according to preset labels.

- [ ] **Step 4: Run green tests**

Run the focused UI tests. Expected: pass.

### Task 4: Final Verification

**Files:**
- All modified files.

- [ ] **Step 1: Run full test suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp .codex-local\pytest-tmp -q
```

Expected: all tests pass.

- [ ] **Step 2: Inspect status**

Run:

```powershell
git status --short --ignored config/settings.json
```

Expected: tracked implementation files modified, local `config/settings.json` ignored.
