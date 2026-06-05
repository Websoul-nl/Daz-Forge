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


def test_main_window_analyzes_source_and_populates_review(qapp, tmp_path: Path) -> None:
    write_file(tmp_path / "Scripts" / "Websoul" / "Tool.dsa", "// script")

    window = MainWindow()
    window.set_source_path(tmp_path)
    window.analyze_current_source()

    assert "script/tool" in window.summary_text()
    assert window.table_model.rowCount() == 1
    assert "Scripts/Websoul/Tool.dsa" in window.current_contract["rows"][0]["path"]
    assert "Hard blockers: 0" in window.issue_text()
