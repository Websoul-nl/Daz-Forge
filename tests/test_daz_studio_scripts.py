from pathlib import Path


SCRIPT_PATH = Path("daz-studio-scripts") / "jcm_gate_repair.dsa"


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_jcm_gate_repair_script_is_checked_in() -> None:
    assert SCRIPT_PATH.exists()


def test_jcm_gate_repair_defaults_to_preview_and_selected_figure_only() -> None:
    script = _script_text()

    assert "Scene.getPrimarySelection()" in script
    assert "var APPLY_CHANGES = false" in script
    assert "var ALLOW_FALLBACK_GATE = false" in script
    assert "Preview only is ON" in script


def test_jcm_gate_repair_adds_multiply_erc_without_auto_saving_assets() -> None:
    script = _script_text()

    assert "new DzERCLink( DzERCLink.ERCMultiply" in script
    assert ".insertController( link" in script
    assert "Save Modified Assets" in script
    assert "saveModifiedAssets" not in script
    assert "doSave" not in script
