import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from forge.analyzer.inference import infer_metadata
from forge.analyzer.inventory import classify_inventory
from forge.analyzer.review_contract import build_review_contract, contract_to_dict
from forge.analyzer.source import scan_source
from forge.ui.main_window import MainWindow
from forge.ui.review_model import ReviewTableModel


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def write_file(path: Path, content: bytes | str = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)


def dson(asset_type: str, author: str = "Websoul") -> bytes:
    return json.dumps(
        {
            "file_version": "0.6.1.0",
            "asset_info": {
                "id": "/People/Genesis%209/Test.duf",
                "type": asset_type,
                "contributor": {"author": author, "email": "", "website": ""},
                "revision": "1.0",
                "modified": "2026-06-05T00:00:00Z",
            },
        }
    ).encode("utf-8")


def review_payload(path: Path) -> dict:
    scan = scan_source(path)
    inventory = classify_inventory(scan)
    inference = infer_metadata(scan, inventory)
    return contract_to_dict(build_review_contract(scan, inventory, inference))


def manual_payload() -> dict:
    return {
        "product": {
            "product_type": "clothing/outfit",
            "primary_artist": "Websoul",
            "artists": ["Websoul"],
            "smart_content_count": 2,
            "total_files": 10,
            "model_provider": "off",
        },
        "warnings": [{"code": "inference-warning", "message": "Dress.duf: support-category-conflict"}],
        "hard_blockers": [],
        "rows": [
            {
                "path": "People/Genesis 9/Clothing/Websoul/Dress.duf",
                "final": {
                    "content_type": "Follower/Wardrobe",
                    "categories": ["/Default/Wardrobe"],
                    "compatibility_base": "",
                    "compatibilities": ["/Genesis 9/Base"],
                    "editable": True,
                },
                "deterministic": {
                    "content_type": "Follower/Wardrobe",
                    "categories": ["/Default/Wardrobe"],
                    "compatibility_base": "",
                    "compatibilities": ["/Genesis 9/Base"],
                    "confidence": 0.8,
                    "reason": "deterministic analyzer",
                },
                "model": {
                    "content_type": "Follower/Wardrobe",
                    "categories": ["/Default/Wardrobe/Dresses"],
                    "compatibility_base": "",
                    "compatibilities": ["/Genesis 9/Base"],
                    "confidence": 0.9,
                    "reason": "Model likes dresses.",
                },
                "support": {
                    "content_type": "Follower/Wardrobe",
                    "categories": ["/Default/Wardrobe"],
                    "compatibility_base": "",
                    "compatibilities": ["/Genesis 9/Base"],
                    "confidence": 1.0,
                    "reason": "existing support file",
                },
                "warnings": ["support-category-conflict"],
                "author": "Websoul",
                "asset_type": "wearable",
            },
            {
                "path": "People/Genesis 9/Clothing/Websoul/Materials/Dress Red.duf",
                "final": {
                    "content_type": "Preset/Materials",
                    "categories": ["/Default/Materials"],
                    "compatibility_base": "",
                    "compatibilities": ["/Genesis 9/Base"],
                    "editable": True,
                },
                "deterministic": {
                    "content_type": "Preset/Materials",
                    "categories": ["/Default/Materials"],
                    "compatibility_base": "",
                    "compatibilities": ["/Genesis 9/Base"],
                    "confidence": 0.8,
                    "reason": "deterministic analyzer",
                },
                "model": None,
                "support": None,
                "warnings": [],
                "author": "Websoul",
                "asset_type": "preset_material",
            },
        ],
    }


def test_table_model_exposes_review_rows_and_headers(tmp_path: Path) -> None:
    write_file(tmp_path / "People" / "Genesis 9" / "Hair" / "Websoul" / "Hero Hair.duf", dson("wearable"))

    model = ReviewTableModel(review_payload(tmp_path))

    assert model.rowCount() == 1
    assert model.columnCount() >= 8
    assert model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "File"
    assert model.data(model.index(0, model.column_index("Content Type")), Qt.ItemDataRole.DisplayRole) == "Follower/Hair"
    assert model.data(model.index(0, model.column_index("Category")), Qt.ItemDataRole.DisplayRole) == "/Default/Hair"


def test_table_model_edits_final_fields(tmp_path: Path) -> None:
    write_file(tmp_path / "People" / "Genesis 9" / "Hair" / "Websoul" / "Hero Hair.duf", dson("wearable"))
    model = ReviewTableModel(review_payload(tmp_path))

    category_index = model.index(0, model.column_index("Category"))
    content_type_index = model.index(0, model.column_index("Content Type"))

    assert model.setData(category_index, "/Default/Hair/Long", Qt.ItemDataRole.EditRole)
    assert model.setData(content_type_index, "Follower/Hair", Qt.ItemDataRole.EditRole)

    approved = model.approved_rows()
    assert approved[0]["final"]["categories"] == ["/Default/Hair/Long"]
    assert approved[0]["final"]["content_type"] == "Follower/Hair"


def test_table_model_filters_by_text_and_warnings_only() -> None:
    model = ReviewTableModel(manual_payload())

    model.set_filter_text("red")

    assert model.rowCount() == 1
    assert "Dress Red.duf" in model.data(model.index(0, model.column_index("File")), Qt.ItemDataRole.DisplayRole)

    model.set_filter_text("")
    model.set_warnings_only(True)

    assert model.rowCount() == 1
    assert "Dress.duf" in model.data(model.index(0, model.column_index("File")), Qt.ItemDataRole.DisplayRole)


def test_table_model_formats_selected_row_details() -> None:
    model = ReviewTableModel(manual_payload())

    details = model.row_details(0)

    assert "People/Genesis 9/Clothing/Websoul/Dress.duf" in details
    assert "Final" in details
    assert "Deterministic" in details
    assert "Model" in details
    assert "support-category-conflict" in details


def test_table_model_can_apply_support_or_mark_row_reviewed() -> None:
    model = ReviewTableModel(manual_payload())

    assert model.apply_support_to_row(0)

    approved = model.approved_rows()
    assert approved[0]["final"]["categories"] == ["/Default/Wardrobe"]
    assert approved[0]["warnings"] == []

    model.set_warnings_only(True)
    assert model.rowCount() == 0

    model.set_warnings_only(False)
    model.setData(model.index(0, model.column_index("Category")), "/Default/Wardrobe/Dresses", Qt.ItemDataRole.EditRole)
    approved = model.approved_rows()
    approved[0]["warnings"] = ["support-category-conflict"]
    model.set_contract({**manual_payload(), "rows": approved})

    assert model.mark_row_reviewed(0)
    assert model.approved_rows()[0]["warnings"] == []


def test_main_window_analyzes_source_and_populates_review(qapp, tmp_path: Path) -> None:
    write_file(tmp_path / "Scripts" / "Websoul" / "Tool.dsa", "// script")

    window = MainWindow()
    window.set_source_path(tmp_path)
    window.analyze_current_source()

    assert "script/tool" in window.summary_text()
    assert window.table_model.rowCount() == 1
    assert "Scripts/Websoul/Tool.dsa" in window.current_contract["rows"][0]["path"]
    assert "Hard blockers: 0" in window.issue_text()


def test_main_window_filter_controls_and_details_panel(qapp) -> None:
    window = MainWindow()
    window.set_contract(manual_payload())

    window.filter_edit.setText("red")

    assert window.table_model.rowCount() == 1
    assert "Showing: 1 / 2" in window.summary_text()

    window.filter_edit.setText("")
    window.warnings_only_checkbox.setChecked(True)
    window.show_row_details(0)

    assert window.table_model.rowCount() == 1
    assert "support-category-conflict" in window.detail_text()


def test_main_window_warning_resolution_buttons(qapp) -> None:
    window = MainWindow()
    window.set_contract(manual_payload())
    window.warnings_only_checkbox.setChecked(True)
    window.table_view.selectRow(0)

    window.mark_selected_row_reviewed()

    assert window.table_model.rowCount() == 0
    assert "Dress.duf: support-category-conflict" not in window.issue_text()
    assert "product" not in window.issue_text()

    window = MainWindow()
    window.set_contract(manual_payload())
    window.issue_list.setCurrentRow(2)
    window.mark_selected_issue_reviewed()

    assert "Dress.duf: support-category-conflict" not in window.issue_text()
