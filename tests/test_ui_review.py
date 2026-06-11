import json
import os
import re
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from forge.analyzer.inference import infer_metadata
from forge.analyzer.inventory import classify_inventory
from forge.analyzer.model_provider import OllamaProvider
from forge.analyzer.review_contract import build_review_contract, contract_to_dict
from forge.analyzer.source import scan_source
from forge.ui.main_window import AnalysisWorker, MainWindow
from forge.ui.main_window import analyze_source
from forge.ui.main_window import _apply_model_suggestion_diffs, _model_diff_label, _model_suggestion_diffs
from forge.ui.delegates import CompactLineEditDelegate, SearchableComboDelegate
from forge.ui.pages.dim_packager_page import DimPackagerPage
from forge.ui.pages.pose_converter_page import PoseConverterPage
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


def test_main_window_wraps_packager_in_first_tab(qapp) -> None:
    window = MainWindow(available_model_providers=())

    assert window.tabs.count() >= 1
    assert window.tabs.tabText(0) == "DIM Packager"
    assert isinstance(window.dim_packager_page, DimPackagerPage)
    assert window.tabs.widget(0) is window.dim_packager_page
    assert _has_ancestor(window.source_edit, window.dim_packager_page)
    assert _has_ancestor(window.build_package_button, window.dim_packager_page)


def test_main_window_adds_pose_converter_tab(qapp) -> None:
    window = MainWindow(available_model_providers=())

    assert window.tabs.count() >= 2
    assert window.tabs.tabText(1) == "Pose Converters"
    assert isinstance(window.pose_converter_page, PoseConverterPage)
    assert _has_ancestor(window.pose_source_edit, window.pose_converter_page)
    assert _has_ancestor(window.pose_product_name_edit, window.pose_converter_page)
    assert _has_ancestor(window.pose_convert_button, window.pose_converter_page)
    assert window.pose_convert_button.objectName() == "primaryPoseConvertButton"


def test_packager_page_uses_product_and_selected_file_inspector_tabs(qapp) -> None:
    window = MainWindow(available_model_providers=())
    page = window.dim_packager_page

    assert page.inspector_tabs.count() == 3
    assert page.inspector_tabs.tabText(0) == "Product"
    assert page.inspector_tabs.tabText(1) == "Product Image"
    assert page.inspector_tabs.tabText(2) == "Selected File"
    assert _has_ancestor(window.product_name_edit, page.product_tab)
    assert _has_ancestor(window.store_combo, page.product_tab)
    assert _has_ancestor(window.product_image_path_edit, page.product_image_tab)
    assert _has_ancestor(window.product_image_drop_zone, page.product_image_tab)
    assert _has_ancestor(window.detail_view, page.selected_file_tab)
    assert _has_ancestor(window.ask_model_button, page.selected_file_tab)
    assert _has_ancestor(window.source_edit, page.source_toolbar)
    assert _has_ancestor(window.analyze_button, page.source_toolbar)
    assert page.footer_layout.itemAt(page.footer_layout.count() - 1).layout() is page.package_action_bar


def test_pose_converter_tab_builds_converted_dim_package(qapp, tmp_path: Path) -> None:
    calls = {}
    source = tmp_path / "IM00083577-01_RoadTripPosesforGenesis8Female.zip"
    source.write_bytes(b"zip-ish")
    output = tmp_path / "out"

    def fake_builder(source_path, output_path, *, metadata):
        calls["source"] = source_path
        calls["output"] = output_path
        calls["metadata"] = metadata
        return SimpleNamespace(
            conversion_report=SimpleNamespace(converted_count=24, skipped_count=0),
            package=SimpleNamespace(zip_path=output_path / "WEB24156031-01_RoadTripPosesforGenesis9.zip"),
        )

    window = MainWindow(available_model_providers=(), pose_package_builder=fake_builder)
    window.set_pose_source_path(source)
    window.pose_output_edit.setText(str(output))
    window.pose_product_name_edit.setText("Road Trip Poses for Genesis 9")
    window.pose_store_combo.setCurrentText("Websoul")
    window.pose_store_prefix_edit.setText("WEB")
    window.pose_store_code_edit.setText("")
    window.pose_token_edit.setText("24156031")
    stale_guid = "11111111-2222-4333-8444-555555555555"
    window.pose_guid_edit.setText(stale_guid)
    window.pose_artists_edit.setText("Websoul")

    window.build_pose_converter_package()

    assert calls["source"] == source
    assert calls["output"] == output
    assert calls["metadata"]["product_name"] == "Road Trip Poses for Genesis 9"
    assert calls["metadata"]["store_id"] == "WEBSOUL"
    assert calls["metadata"]["store_prefix"] == "WEB"
    assert calls["metadata"]["product_token"] == "24156031"
    assert calls["metadata"]["global_id"] != stale_guid
    assert calls["metadata"]["global_id"] == window.pose_guid_edit.text()
    assert calls["metadata"]["artists"] == ["Websoul"]
    assert "Converted 24 pose file(s)" in window.pose_status_text.toPlainText()
    assert "WEB24156031-01_RoadTripPosesforGenesis9.zip" in window.pose_status_text.toPlainText()


def test_pose_converter_prefills_readable_product_name_from_support_file(qapp, tmp_path: Path) -> None:
    source = tmp_path / "IM00083577-01_RoadTripPosesforGenesis8Female.zip"
    with ZipFile(source, "w") as archive:
        archive.writestr(
            "Content/Runtime/Support/DAZ_3D_83577_Road_Trip_Poses_for_Genesis_8_Female.dsx",
            """
            <ContentDBInstall VERSION="1.0">
              <Products>
                <Product VALUE="Road Trip Poses for Genesis 8 Female">
                  <StoreID VALUE="DAZ 3D"/>
                </Product>
              </Products>
            </ContentDBInstall>
            """,
        )
        archive.writestr(
            "Content/People/Genesis 8 Female/Poses/Road Trip Poses for Genesis 8 Female/Road Trip 01.duf",
            dson("preset_pose"),
        )

    window = MainWindow(available_model_providers=())
    window.set_pose_source_path(source)

    assert window.pose_product_name_edit.text() == "Road Trip Poses for Genesis 9"


def _has_ancestor(widget: QWidget, ancestor: QWidget) -> bool:
    current: QWidget | None = widget
    while current is not None:
        if current is ancestor:
            return True
        current = current.parentWidget()
    return False


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


def test_table_model_can_apply_model_suggestion() -> None:
    model = ReviewTableModel(manual_payload())

    assert model.apply_model_to_row(0)

    approved = model.approved_rows()
    assert approved[0]["final"]["categories"] == ["/Default/Wardrobe/Dresses"]
    assert approved[0]["warnings"] == []


class StaticProvider:
    name = "fake-model"
    model = "local-test"

    def suggest(self, packet):
        return {
            "suggestions": [
                {
                    "path": "Scripts/Websoul/Tool.dsa",
                    "content_type": "Script/Utility",
                    "categories": ["/Default/Utilities/Scripts"],
                    "compatibility_base": "",
                    "compatibilities": [],
                    "confidence": 0.7,
                    "reason": "Script path is a utility.",
                }
            ]
        }


class TimedOllamaProvider(StaticProvider):
    name = "ollama"
    model = "qwen3:4b"
    timeout_seconds = 35


class ChangeProvider(StaticProvider):
    def suggest(self, packet):
        return {
            "suggestions": [
                {
                    "path": "Scripts/Websoul/Tool.dsa",
                    "content_type": "Script/Utility",
                    "categories": ["/Default/Scripts/Utilities"],
                    "compatibility_base": "",
                    "compatibilities": [],
                    "confidence": 0.7,
                    "reason": "A deliberately different script category.",
                }
            ]
        }


def test_analyze_source_can_include_model_suggestions(tmp_path: Path) -> None:
    write_file(tmp_path / "Scripts" / "Websoul" / "Tool.dsa", "// script")

    payload = analyze_source(tmp_path, provider=StaticProvider())

    assert payload["product"]["model_provider"] == "fake-model"
    assert payload["product"]["model_available"] is True
    assert payload["rows"][0]["model"]["categories"] == ["/Default/Utilities/Scripts"]


def test_analyze_source_reports_progress_messages(tmp_path: Path) -> None:
    write_file(tmp_path / "Scripts" / "Websoul" / "Tool.dsa", "// script")
    messages = []

    payload = analyze_source(tmp_path, progress=messages.append)

    assert payload["product"]["smart_content_count"] == 1
    assert messages[0] == "Scanning source..."
    assert "Classifying files... 1 / 1" in messages
    assert "Inferring metadata... 1 / 1" in messages
    assert "Building review grid..." in messages
    assert messages[-1] == "Ready: 1 rows, 0 blockers, 1 warnings"


def test_analyze_source_progress_names_model_provider(tmp_path: Path) -> None:
    write_file(tmp_path / "Scripts" / "Websoul" / "Tool.dsa", "// script")
    messages = []

    analyze_source(tmp_path, provider=StaticProvider(), progress=messages.append)

    assert "Asking fake-model local-test... 1 / 1" in messages


def test_analyze_source_progress_shows_friendly_provider_timeout(tmp_path: Path) -> None:
    write_file(tmp_path / "Scripts" / "Websoul" / "Tool.dsa", "// script")
    messages = []

    analyze_source(tmp_path, provider=TimedOllamaProvider(), progress=messages.append)

    assert "Asking Ollama qwen3:4b (up to 35s)... 1 / 1" in messages


def test_main_window_analyzes_source_and_populates_review(qapp, tmp_path: Path) -> None:
    write_file(tmp_path / "Scripts" / "Websoul" / "Tool.dsa", "// script")

    window = MainWindow(run_analysis_synchronously=True)
    window.provider_combo.setCurrentText("Off")
    window.set_source_path(tmp_path)
    window.analyze_current_source()

    assert "script/tool" in window.summary_text()
    assert window.table_model.rowCount() == 1
    assert "Scripts/Websoul/Tool.dsa" in window.current_contract["rows"][0]["path"]
    assert "Hard blockers: 0" in window.issue_text()
    assert window.statusBar().currentMessage() == "Ready: 1 rows, 0 blockers, 1 warnings"


def test_main_window_prefills_product_metadata_fields(qapp, tmp_path: Path) -> None:
    product_root = tmp_path / "Hero Product"
    write_file(product_root / "Props" / "Websoul" / "Tool.duf", dson("scene_subset"))

    window = MainWindow(run_analysis_synchronously=True)
    window.set_source_path(product_root)
    window.analyze_current_source()

    assert window.product_name_edit.text() == "Hero Product"
    assert window.store_combo.currentText() == "Websoul"
    assert window.store_prefix_edit.text() == "WEB"
    assert window.store_code_edit.text() == ""
    assert window.token_edit.text() == "24156030"
    assert window.artists_edit.text() == "Websoul"
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", window.guid_edit.text())
    assert window.current_contract["product"]["product_token"] == "24156030"
    assert window.current_contract["product"]["global_id"] == window.guid_edit.text()


def test_main_window_product_metadata_edits_update_contract(qapp) -> None:
    window = MainWindow(available_model_providers=())
    window.set_contract(manual_payload())

    window.product_name_edit.setText("Better Product")
    window.store_combo.setEditText("Renderosity")
    window.store_prefix_edit.setText("RND")
    window.store_code_edit.setText("SADE")
    window.token_edit.setText("12345678")
    window.guid_edit.setText("bf8660f0-d6be-4171-abdd-19a3315e4170")
    window.artists_edit.setText("Sade; Websoul")

    product = window.current_contract["product"]
    assert product["product_name"] == "Better Product"
    assert product["store_display_name"] == "Renderosity"
    assert product["store_id"] == "Renderosity"
    assert product["store_prefix"] == "RND"
    assert product["store_code"] == "SADE"
    assert product["product_token"] == "12345678"
    assert product["global_id"] == "bf8660f0-d6be-4171-abdd-19a3315e4170"
    assert product["primary_artist"] == "Sade"
    assert product["artists"] == ["Sade", "Websoul"]


def test_main_window_store_dropdown_fills_prefix_field(qapp) -> None:
    window = MainWindow(available_model_providers=())
    window.set_contract(manual_payload())

    window.store_combo.setCurrentText("3D SHARDS")

    assert window.store_prefix_edit.text() == "SHA"
    assert window.current_contract["product"]["store_display_name"] == "3D SHARDS"
    assert window.current_contract["product"]["store_id"] == "3D SHARDS"
    assert window.current_contract["product"]["store_prefix"] == "SHA"


def test_main_window_can_generate_new_product_guid(qapp) -> None:
    window = MainWindow(available_model_providers=())
    window.set_contract(manual_payload())
    old_guid = window.guid_edit.text()

    window.generate_product_guid()

    assert window.guid_edit.text() != old_guid
    assert window.current_contract["product"]["global_id"] == window.guid_edit.text()


def test_main_window_package_actions_are_bottom_accent_and_open_output(qapp, tmp_path: Path) -> None:
    opened = []
    source = tmp_path / "Hero Product"
    source.mkdir()
    window = MainWindow(available_model_providers=(), output_folder_opener=opened.append)
    window.set_source_path(source)

    assert window.build_package_button.objectName() == "primaryBuildPackageButton"
    assert window.go_to_output_folder_button.text() == "Go to Output Folder"
    assert window.dim_packager_page.footer_layout.itemAt(
        window.dim_packager_page.footer_layout.count() - 1
    ).layout() is window.package_action_bar

    window.open_output_folder()

    assert opened == [tmp_path / "Daz Forge Packages"]


def test_main_window_prefills_product_metadata_from_support_file(qapp, tmp_path: Path) -> None:
    write_file(tmp_path / "Props" / "Sadriel" / "Jewelry.duf", dson("scene_subset", author="Sadriel"))
    write_file(
        tmp_path / "Runtime" / "Support" / "LOCAL_USER_Celtic_Jewelry.dsx",
        """
        <ContentDBInstall VERSION="1.0">
          <Products>
            <Product VALUE="Celtic Jewelry for Genesis 8 and 9">
              <StoreID VALUE="LOCAL USER"/>
              <GlobalID VALUE="bf8660f0-d6be-4171-abdd-19a3315e4170"/>
              <ProductToken VALUE="884422"/>
              <Artists>
                <Artist VALUE="Sade"/>
                <Artist VALUE="Sadriel"/>
              </Artists>
            </Product>
          </Products>
        </ContentDBInstall>
        """,
    )

    window = MainWindow(run_analysis_synchronously=True)
    window.set_source_path(tmp_path)
    window.analyze_current_source()

    assert window.product_name_edit.text() == "Celtic Jewelry for Genesis 8 and 9"
    assert window.store_combo.currentText() == "LOCAL USER"
    assert window.store_prefix_edit.text() == "LU"
    assert window.store_code_edit.text() == ""
    assert window.guid_edit.text() == "bf8660f0-d6be-4171-abdd-19a3315e4170"
    assert window.token_edit.text() == "884422"
    assert window.artists_edit.text() == "Sade; Sadriel"


def test_main_window_prefills_product_image_from_support_image(qapp, tmp_path: Path) -> None:
    write_file(tmp_path / "Props" / "Sadriel" / "Jewelry.duf", dson("scene_subset", author="Sadriel"))
    write_file(
        tmp_path / "Runtime" / "Support" / "LOCAL_USER_Celtic_Jewelry.dsx",
        """
        <ContentDBInstall VERSION="1.0">
          <Products><Product VALUE="Celtic Jewelry"/></Products>
        </ContentDBInstall>
        """,
    )
    write_file(tmp_path / "Runtime" / "Support" / "LOCAL_USER_Celtic_Jewelry.png", b"not a real png")

    window = MainWindow(run_analysis_synchronously=True)
    window.set_source_path(tmp_path)
    window.analyze_current_source()

    assert window.product_image_path_edit.text() == "Runtime/Support/LOCAL_USER_Celtic_Jewelry.png"
    assert window.current_contract["product"]["product_image"] == "Runtime/Support/LOCAL_USER_Celtic_Jewelry.png"


def test_main_window_product_image_picker_updates_contract(qapp, tmp_path: Path) -> None:
    image_path = tmp_path / "cover.jpg"
    write_file(image_path, b"image-ish")
    window = MainWindow(available_model_providers=())

    window.set_product_image_path(image_path)

    assert window.product_image_path_edit.text() == str(image_path)
    assert window.current_contract["product"]["product_image"] == str(image_path)


def test_product_image_drop_zone_updates_contract(qapp, tmp_path: Path) -> None:
    image_path = tmp_path / "drop.png"
    write_file(image_path, b"image-ish")
    window = MainWindow(available_model_providers=())

    window.product_image_drop_zone.handle_dropped_path(image_path)

    assert window.product_image_path_edit.text() == str(image_path)
    assert window.current_contract["product"]["product_image"] == str(image_path)


def test_main_window_status_bar_can_show_analysis_progress(qapp) -> None:
    window = MainWindow(available_model_providers=())

    window._analysis_progress("Classifying files... 5 / 34")

    assert window.statusBar().currentMessage() == "Classifying files... 5 / 34"


def test_main_window_starts_analysis_without_blocking_ui(qapp, tmp_path: Path) -> None:
    write_file(tmp_path / "Scripts" / "Websoul" / "Tool.dsa", "// script")
    window = MainWindow()
    started = {}

    def fake_start(source, provider) -> None:
        started["source"] = source
        started["provider"] = provider

    window._start_analysis = fake_start
    window.set_source_path(tmp_path)

    window.analyze_current_source()

    assert started["source"] == tmp_path
    assert started["provider"] is None


def test_main_window_busy_state_disables_analysis_controls(qapp) -> None:
    window = MainWindow()

    window._set_analyzing(True)

    assert window.browse_button.isEnabled() is False
    assert window.source_edit.isEnabled() is False
    assert window.analyze_button.isEnabled() is False
    assert window.ask_model_button.isEnabled() is False

    window._set_analyzing(False)

    assert window.browse_button.isEnabled() is True
    assert window.source_edit.isEnabled() is True
    assert window.analyze_button.isEnabled() is True
    assert window.ask_model_button.isEnabled() is True


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


def test_main_window_loads_source_without_model_provider(qapp, tmp_path: Path) -> None:
    write_file(tmp_path / "Scripts" / "Websoul" / "Tool.dsa", "// script")

    def factory(provider_key, model_name):
        raise AssertionError("source loading should not ask the model")

    window = MainWindow(model_provider_factory=factory, run_analysis_synchronously=True)
    window.set_source_path(tmp_path)

    window.analyze_current_source()

    assert window.current_contract["product"]["model_provider"] == ""
    assert window.current_contract["rows"][0]["model"] is None


def test_main_window_can_ask_configured_model_provider(qapp, tmp_path: Path) -> None:
    write_file(tmp_path / "Scripts" / "Websoul" / "Tool.dsa", "// script")
    requested = {}
    captured = {}

    def factory(provider_key, model_name):
        requested["provider_key"] = provider_key
        requested["model_name"] = model_name
        return StaticProvider()

    window = MainWindow(model_provider_factory=factory, run_analysis_synchronously=True)
    window._show_model_suggestions = lambda contract: captured.setdefault("contract", contract)
    window.set_source_path(tmp_path)
    window.analyze_current_source()

    window.ask_model_for_current_source()

    assert requested == {"provider_key": "ollama", "model_name": "qwen3:4b"}
    assert captured["contract"]["product"]["model_provider"] == "fake-model"
    assert captured["contract"]["rows"][0]["model"]["reason"] == "Script path is a utility."


def test_main_window_has_source_analyze_and_ask_model_actions(qapp) -> None:
    window = MainWindow(available_model_providers=("ollama",))

    assert window.analyze_button.text() == "Analyze"
    assert window.ask_model_button.text() == "Ask Model"


def test_model_provider_controls_default_to_ollama_and_can_be_disabled(qapp) -> None:
    window = MainWindow(available_model_providers=("ollama", "lm-studio"))

    assert window.provider_combo.currentText() == "Ollama"
    assert window.model_name_edit.text() == "qwen3:4b"
    assert window.model_name_edit.isEnabled() is True
    assert window.ask_model_button.isEnabled() is True

    window.provider_combo.setCurrentText("Off")

    assert window.model_name_edit.isEnabled() is False
    assert window.ask_model_button.isEnabled() is False


def test_model_provider_switch_updates_default_model_name(qapp) -> None:
    window = MainWindow(available_model_providers=("ollama", "lm-studio"))

    window.provider_combo.setCurrentText("LM Studio")

    assert window.model_name_edit.text() == "qwen/qwen3-4b"


def test_model_provider_selector_hides_not_installed_providers(qapp) -> None:
    window = MainWindow(available_model_providers=("ollama",))

    options = [window.provider_combo.itemText(index) for index in range(window.provider_combo.count())]

    assert options == ["Ollama", "Off"]
    assert window.provider_combo.currentText() == "Ollama"


def test_analysis_worker_emits_deterministic_contract_before_model_contract(qapp, tmp_path: Path) -> None:
    write_file(tmp_path / "Scripts" / "Websoul" / "Tool.dsa", "// script")
    worker = AnalysisWorker(tmp_path, provider=StaticProvider())
    deterministic_payloads = []
    final_payloads = []

    worker.deterministic_finished.connect(deterministic_payloads.append)
    worker.finished.connect(final_payloads.append)

    worker.run()

    assert len(deterministic_payloads) == 1
    assert deterministic_payloads[0]["product"]["model_provider"] == ""
    assert deterministic_payloads[0]["rows"][0]["model"] is None
    assert len(final_payloads) == 1
    assert final_payloads[0]["product"]["model_provider"] == "fake-model"
    assert final_payloads[0]["rows"][0]["model"]["reason"] == "Script path is a utility."


def test_main_window_merges_model_result_without_overwriting_user_edits(qapp, tmp_path: Path) -> None:
    write_file(tmp_path / "Scripts" / "Websoul" / "Tool.dsa", "// script")
    window = MainWindow(available_model_providers=())
    deterministic_payload = analyze_source(tmp_path)
    model_payload = analyze_source(tmp_path, provider=StaticProvider())

    window.set_contract(deterministic_payload)
    category_index = window.table_model.index(0, window.table_model.column_index("Category"))
    assert window.table_model.setData(category_index, "/Default/Custom/Scripts", Qt.ItemDataRole.EditRole)

    window._analysis_finished(model_payload)

    assert window.table_model.approved_rows()[0]["final"]["categories"] == ["/Default/Custom/Scripts"]
    assert window.table_model.approved_rows()[0]["model"]["categories"] == ["/Default/Utilities/Scripts"]
    assert window.current_contract["product"]["model_provider"] == "fake-model"


def test_model_suggestion_diffs_show_only_model_changes(tmp_path: Path) -> None:
    write_file(tmp_path / "Scripts" / "Websoul" / "Tool.dsa", "// script")
    deterministic_payload = analyze_source(tmp_path)
    model_payload = analyze_source(tmp_path, provider=ChangeProvider())

    diffs = _model_suggestion_diffs(deterministic_payload, model_payload)

    assert diffs == [
        {
            "path": "Scripts/Websoul/Tool.dsa",
            "field": "categories",
            "current": ["/Default/Utilities/Scripts"],
            "suggested": ["/Default/Scripts/Utilities"],
        }
    ]


def test_apply_model_suggestion_diffs_copies_checked_findings_only(tmp_path: Path) -> None:
    write_file(tmp_path / "Scripts" / "Websoul" / "Tool.dsa", "// script")
    deterministic_payload = analyze_source(tmp_path)
    model_payload = analyze_source(tmp_path, provider=ChangeProvider())
    diffs = _model_suggestion_diffs(deterministic_payload, model_payload)

    updated = _apply_model_suggestion_diffs(deterministic_payload, diffs)

    assert updated["rows"][0]["final"]["categories"] == ["/Default/Scripts/Utilities"]
    assert deterministic_payload["rows"][0]["final"]["categories"] == ["/Default/Utilities/Scripts"]


def test_model_suggestion_diffs_block_risky_outfit_changes() -> None:
    deterministic_payload = {
        "rows": [
            {
                "path": "People/Genesis 9/Clothing/PandyGirl/Darcy Outfit/Darcy Button.duf",
                "final": {
                    "categories": ["/Default/Wardrobe"],
                    "compatibility_base": "",
                },
            },
            {
                "path": "People/Genesis 9/Clothing/PandyGirl/Darcy Outfit/Materials/Iray/Darcy !Clear All.duf",
                "final": {
                    "categories": ["/Default/Materials"],
                    "compatibility_base": "",
                },
            },
            {
                "path": "People/Genesis 9/Clothing/PandyGirl/Darcy Outfit/Darcy !Simulation Plane.duf",
                "final": {
                    "categories": ["/Default/Wardrobe"],
                    "compatibility_base": "/Genesis 9/Base",
                },
            },
        ]
    }
    model_payload = {
        "rows": [
            {
                "path": "People/Genesis 9/Clothing/PandyGirl/Darcy Outfit/Darcy Button.duf",
                "model": {
                    "categories": ["/Default/Scenes"],
                    "compatibility_base": "/Genesis 9",
                },
            },
            {
                "path": "People/Genesis 9/Clothing/PandyGirl/Darcy Outfit/Materials/Iray/Darcy !Clear All.duf",
                "model": {
                    "categories": ["/Default/Shaders"],
                    "compatibility_base": "/Genesis 9",
                },
            },
            {
                "path": "People/Genesis 9/Clothing/PandyGirl/Darcy Outfit/Darcy !Simulation Plane.duf",
                "model": {
                    "categories": ["/Default/Wardrobe"],
                    "compatibility_base": "/Genesis 9",
                },
            },
        ]
    }

    diffs = _model_suggestion_diffs(deterministic_payload, model_payload)

    assert len(diffs) == 5
    assert {diff["field"] for diff in diffs} == {"categories", "compatibility_base"}
    assert all(diff["risk"] == "blocked" for diff in diffs)
    assert {reason for diff in diffs for reason in diff["risk_reasons"]} == {
        "category conflicts with clothing path",
        "category conflicts with materials path",
        "model added compatibility base",
        "model shortened compatibility base",
    }


def test_apply_model_suggestion_diffs_skips_blocked_findings() -> None:
    payload = {
        "rows": [
            {
                "path": "People/Genesis 9/Clothing/PandyGirl/Darcy Outfit/Darcy Button.duf",
                "final": {
                    "categories": ["/Default/Wardrobe"],
                    "compatibility_base": "",
                },
            }
        ]
    }
    diffs = [
        {
            "path": "People/Genesis 9/Clothing/PandyGirl/Darcy Outfit/Darcy Button.duf",
            "field": "categories",
            "current": ["/Default/Wardrobe"],
            "suggested": ["/Default/Scenes"],
            "risk": "blocked",
            "risk_reasons": ["category conflicts with clothing path"],
        }
    ]

    updated = _apply_model_suggestion_diffs(payload, diffs)

    assert updated["rows"][0]["final"]["categories"] == ["/Default/Wardrobe"]


def test_model_diff_label_marks_blocked_suggestions() -> None:
    label = _model_diff_label(
        {
            "path": "People/Genesis 9/Clothing/PandyGirl/Darcy Outfit/Darcy Button.duf",
            "field": "categories",
            "current": ["/Default/Wardrobe"],
            "suggested": ["/Default/Scenes"],
            "risk": "blocked",
            "risk_reasons": ["category conflicts with clothing path"],
        }
    )

    assert label.startswith("BLOCKED (category conflicts with clothing path)")


def test_ollama_default_provider_has_timeout_for_background_analysis(qapp) -> None:
    window = MainWindow(available_model_providers=("ollama",))

    provider = window._default_model_provider_factory("ollama", "qwen3:4b")

    assert isinstance(provider, OllamaProvider)
    assert provider.timeout_seconds == 120


def test_model_provider_selector_falls_back_to_off_when_none_installed(qapp) -> None:
    window = MainWindow(available_model_providers=())

    options = [window.provider_combo.itemText(index) for index in range(window.provider_combo.count())]

    assert options == ["Off"]
    assert window.provider_combo.currentText() == "Off"
    assert window.model_name_edit.isEnabled() is False
    assert window.ask_model_button.isEnabled() is False


def test_content_type_column_uses_searchable_picker(qapp) -> None:
    window = MainWindow()
    delegate = window.table_view.itemDelegateForColumn(window.table_model.column_index("Content Type"))

    assert isinstance(delegate, SearchableComboDelegate)
    assert "Follower/Accessory" in delegate.options
    assert "Preset/Materials" in delegate.options


def test_editable_text_columns_use_compact_table_editor(qapp) -> None:
    window = MainWindow()

    for column_name in ("Category", "Compatibility Base", "Compatibilities"):
        delegate = window.table_view.itemDelegateForColumn(window.table_model.column_index(column_name))
        assert isinstance(delegate, CompactLineEditDelegate)

    window = MainWindow()
    window.set_contract(manual_payload())
    window.issue_list.setCurrentRow(2)
    window.mark_selected_issue_reviewed()

    assert "Dress.duf: support-category-conflict" not in window.issue_text()
