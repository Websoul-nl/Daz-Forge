from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import re
import shutil
from typing import Any, Callable
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QTableView,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from forge.analyzer.inference import infer_metadata
from forge.analyzer.inference import InferenceResult
from forge.analyzer.inventory import classify_inventory
from forge.analyzer.inventory import InventoryResult
from forge.analyzer.model_provider import (
    LMStudioProvider,
    MetadataSuggestionProvider,
    ModelSuggestionResult,
    OllamaProvider,
    build_model_packet,
    request_model_suggestions,
)
from forge.analyzer.review_contract import build_review_contract, contract_to_dict
from forge.analyzer.source import SourceScan, scan_source
from forge.packager.dim import build_dim_package
from forge.pose_converter.product import build_converted_pose_dim_package
from forge.settings import AppSettings, StoreSettings, load_store_catalog, upsert_store
from forge.ui.delegates import CONTENT_TYPE_OPTIONS, CompactLineEditDelegate, SearchableComboDelegate
from forge.ui.pages.dim_packager_page import DimPackagerPage
from forge.ui.pages.pose_converter_page import PoseConverterPage
from forge.ui.review_model import ReviewTableModel


class AnalysisWorker(QObject):
    progress = Signal(str)
    deterministic_finished = Signal(dict)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, source: Path, provider: MetadataSuggestionProvider | None = None) -> None:
        super().__init__()
        self.source = source
        self.provider = provider

    @Slot()
    def run(self) -> None:
        try:
            context = _analyze_source_context(self.source, progress=self.progress.emit)
            if self.provider is None:
                self.finished.emit(_build_analysis_payload(context, progress=self.progress.emit))
                return
            self.deterministic_finished.emit(_build_analysis_payload(context, progress=self.progress.emit))
            model_result = _request_model_result(self.provider, context, progress=self.progress.emit)
            self.finished.emit(_build_analysis_payload(context, model_result, progress=self.progress.emit))
        except Exception as exc:
            self.failed.emit(str(exc))


@dataclass(frozen=True)
class AnalysisContext:
    scan: SourceScan
    inventory: InventoryResult
    inference: InferenceResult


class ModelSuggestionDialog(QDialog):
    def __init__(self, diffs: list[dict[str, Any]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Model Suggestions")
        self.resize(720, 420)
        self.diff_list = QListWidget()
        for diff in diffs:
            item = QListWidgetItem(_model_diff_label(diff))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            if _is_blocked_model_diff(diff):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip("; ".join(diff.get("risk_reasons", [])))
            item.setData(Qt.ItemDataRole.UserRole, diff)
            self.diff_list.addItem(item)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Apply Checked")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose which model suggestions to copy into the grid."))
        layout.addWidget(self.diff_list, 1)
        layout.addWidget(buttons)

    def selected_diffs(self) -> list[dict[str, Any]]:
        selected = []
        for index in range(self.diff_list.count()):
            item = self.diff_list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(deepcopy(item.data(Qt.ItemDataRole.UserRole)))
        return selected


class MainWindow(QMainWindow):
    def __init__(
        self,
        model_provider_factory: Callable[[str, str], MetadataSuggestionProvider] | None = None,
        available_model_providers: tuple[str, ...] | None = None,
        app_settings: AppSettings | None = None,
        store_catalog_path: Path | None = None,
        run_analysis_synchronously: bool = False,
        output_folder_opener: Callable[[Path], None] | None = None,
        pose_package_builder: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Daz Forge")
        self.resize(1320, 780)
        self.setAcceptDrops(True)

        self._analyzing = False
        self.analysis_thread: QThread | None = None
        self.analysis_worker: AnalysisWorker | None = None
        self.run_analysis_synchronously = run_analysis_synchronously
        self.app_settings = app_settings or AppSettings.defaults()
        self.store_catalog_path = store_catalog_path or _default_store_catalog_path()
        self.store_catalog = list(load_store_catalog(self.store_catalog_path))
        self._syncing_product_fields = False
        self.current_contract: dict[str, Any] = {"rows": [], "warnings": [], "hard_blockers": []}
        self.table_model = ReviewTableModel(self.current_contract)
        self.model_provider_factory = model_provider_factory or self._default_model_provider_factory
        self.output_folder_opener = output_folder_opener or _open_folder_with_desktop
        self.pose_package_builder = pose_package_builder or build_converted_pose_dim_package
        self.available_model_providers = (
            available_model_providers
            if available_model_providers is not None
            else self._detect_available_model_providers()
        )

        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Select a product folder or zip")
        self.browse_button = QPushButton("Browse")
        self.analyze_button = QPushButton("Analyze")
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter rows")
        self.warnings_only_checkbox = QCheckBox("Warnings only")
        self.product_name_edit = QLineEdit()
        self.product_name_edit.setPlaceholderText("Product name")
        self.store_combo = QComboBox()
        self.store_combo.setEditable(True)
        self.store_combo.addItems([store.display_name for store in self.store_catalog])
        self.store_prefix_edit = QLineEdit()
        self.store_prefix_edit.setPlaceholderText("Prefix")
        self.store_code_edit = QLineEdit()
        self.store_code_edit.setPlaceholderText("Code")
        self.token_edit = QLineEdit()
        self.token_edit.setPlaceholderText("Token")
        self.guid_edit = QLineEdit()
        self.guid_edit.setPlaceholderText("GUID")
        self.generate_guid_button = QPushButton("Generate")
        self.artists_edit = QLineEdit()
        self.artists_edit.setPlaceholderText("Artists")
        self.product_image_path_edit = QLineEdit()
        self.product_image_path_edit.setPlaceholderText("No product image selected")
        self.choose_product_image_button = QPushButton("Choose Image")
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(self._provider_labels())
        self.provider_combo.setCurrentText(self._default_provider_label())
        self.model_name_edit = QLineEdit(self._default_model_name(self.provider_combo.currentText()))
        self.model_name_edit.setPlaceholderText("Model")
        self.model_name_edit.setMinimumWidth(220)
        self.ask_model_button = QPushButton("Ask Model")
        self.build_package_button = QPushButton("Build Package")
        self.build_package_button.setObjectName("primaryBuildPackageButton")
        self.go_to_output_folder_button = QPushButton("Go to Output Folder")
        self.use_support_button = QPushButton("Use Support")
        self.mark_row_reviewed_button = QPushButton("Mark Row Reviewed")
        self.mark_issue_reviewed_button = QPushButton("Mark Issue Reviewed")
        self.pose_source_edit = QLineEdit()
        self.pose_source_edit.setPlaceholderText("Select a Genesis 8 Female pose product zip or folder")
        self.pose_browse_source_button = QPushButton("Browse")
        self.pose_output_edit = QLineEdit()
        self.pose_output_edit.setPlaceholderText("Output folder")
        self.pose_browse_output_button = QPushButton("Output")
        self.pose_open_output_button = QPushButton("Go to Output Folder")
        self.pose_product_name_edit = QLineEdit()
        self.pose_product_name_edit.setPlaceholderText("Converted product name")
        self.pose_store_combo = QComboBox()
        self.pose_store_combo.setEditable(True)
        self.pose_store_combo.addItems([store.display_name for store in self.store_catalog])
        self.pose_store_combo.setCurrentText(self.app_settings.default_store.display_name)
        self.pose_store_prefix_edit = QLineEdit(self.app_settings.default_store.dim_prefix)
        self.pose_store_prefix_edit.setPlaceholderText("Prefix")
        self.pose_store_code_edit = QLineEdit(self.app_settings.default_store.default_code)
        self.pose_store_code_edit.setPlaceholderText("Code")
        self.pose_token_edit = QLineEdit(str(self.app_settings.next_product_number))
        self.pose_token_edit.setPlaceholderText("Token")
        self.pose_guid_edit = QLineEdit(str(uuid4()))
        self.pose_guid_edit.setPlaceholderText("GUID")
        self.pose_artists_edit = QLineEdit(self.app_settings.default_store.display_name)
        self.pose_artists_edit.setPlaceholderText("Artists")
        self.pose_convert_button = QPushButton("Build Converted DIM Package")
        self.pose_convert_button.setObjectName("primaryPoseConvertButton")
        self.pose_status_text = QTextEdit()
        self.pose_status_text.setPlaceholderText("Conversion status")
        self.summary_label = QLabel("No source analyzed")
        self.summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.issue_list = QListWidget()
        self.detail_view = QTextEdit()
        self.detail_view.setReadOnly(True)
        self.reviewed_issue_messages: set[str] = set()
        self.table_view = QTableView()
        self.table_view.setModel(self.table_model)
        self.table_view.setItemDelegateForColumn(
            self.table_model.column_index("Content Type"),
            SearchableComboDelegate(CONTENT_TYPE_OPTIONS, self.table_view),
        )
        compact_text_delegate = CompactLineEditDelegate(self.table_view)
        for column_name in ("Category", "Compatibility Base", "Compatibilities"):
            self.table_view.setItemDelegateForColumn(
                self.table_model.column_index(column_name),
                compact_text_delegate,
            )
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSortingEnabled(False)
        self.table_view.setWordWrap(False)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.verticalHeader().setDefaultSectionSize(28)

        self._build_layout()
        self._connect_signals()
        self._update_model_controls()
        self.statusBar().showMessage("Ready")
        self._apply_style()

    def set_source_path(self, path: Path) -> None:
        self.source_edit.setText(str(path))

    def analyze_current_source(self) -> None:
        if self._analyzing:
            return
        source_text = self.source_edit.text().strip()
        if not source_text:
            self._set_issue_lines(["No source selected."])
            return
        source = Path(source_text)
        if self.run_analysis_synchronously:
            self._run_analysis_synchronously(source, None)
        else:
            self._start_analysis(source, None)

    def set_contract(self, contract: dict[str, Any]) -> None:
        self.current_contract = contract
        self._ensure_product_metadata()
        self._populate_product_fields()
        self.reviewed_issue_messages = set()
        self.table_model.set_contract(self.current_contract)
        self.summary_label.setText(self.summary_text())
        self._set_issue_lines(self._issue_lines())
        self.table_view.resizeColumnsToContents()
        self.show_row_details(0 if self.table_model.rowCount() else -1)

    def summary_text(self) -> str:
        product = self.current_contract.get("product", {})
        if not product:
            return "No source analyzed"
        artists = ", ".join(product.get("artists", [])) or "-"
        return (
            f"Type: {product.get('product_type', '-')}    "
            f"Artist: {product.get('primary_artist') or artists}    "
            f"Rows: {product.get('smart_content_count', 0)}    "
            f"Showing: {self.table_model.visible_row_count()} / {self.table_model.total_row_count()}    "
            f"Files: {product.get('total_files', 0)}    "
            f"Model: {product.get('model_provider') or 'off'}"
        )

    def issue_text(self) -> str:
        return "\n".join(self._issue_lines())

    def detail_text(self) -> str:
        return self.detail_view.toPlainText()

    def show_row_details(self, visible_row: int) -> None:
        self.detail_view.setPlainText(self.table_model.row_details(visible_row))

    def apply_support_to_selected_row(self) -> None:
        if self.table_model.apply_support_to_row(self.table_view.currentIndex().row()):
            self._after_warning_resolution()

    def mark_selected_row_reviewed(self) -> None:
        if self.table_model.mark_row_reviewed(self.table_view.currentIndex().row()):
            self._after_warning_resolution()

    def mark_selected_issue_reviewed(self) -> None:
        item = self.issue_list.currentItem()
        if item is None:
            return
        message = item.data(Qt.ItemDataRole.UserRole)
        if message:
            self.reviewed_issue_messages.add(str(message))
            self._set_issue_lines(self._issue_lines())

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if not urls:
            return
        local_path = urls[0].toLocalFile()
        if local_path:
            self.set_source_path(Path(local_path))
            self.analyze_current_source()

    def _build_layout(self) -> None:
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.dim_packager_page = DimPackagerPage(self)
        self.detail_layout = self.dim_packager_page.detail_layout
        self.package_action_bar = self.dim_packager_page.package_action_bar
        self.tabs.addTab(self.dim_packager_page, "DIM Packager")
        self.pose_converter_page = PoseConverterPage(self)
        self.tabs.addTab(self.pose_converter_page, "Pose Converters")

    def _connect_signals(self) -> None:
        self.browse_button.clicked.connect(self._browse_source)
        self.analyze_button.clicked.connect(self.analyze_current_source)
        self.source_edit.returnPressed.connect(self.analyze_current_source)
        for product_field in (
            self.product_name_edit,
            self.store_prefix_edit,
            self.store_code_edit,
            self.token_edit,
            self.guid_edit,
            self.artists_edit,
        ):
            product_field.textChanged.connect(self._product_metadata_changed)
        self.store_combo.currentTextChanged.connect(self._store_changed)
        self.generate_guid_button.clicked.connect(self.generate_product_guid)
        self.choose_product_image_button.clicked.connect(self.choose_product_image)
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.warnings_only_checkbox.toggled.connect(self._apply_filter)
        self.provider_combo.currentTextChanged.connect(self._provider_changed)
        self.ask_model_button.clicked.connect(self.ask_model_for_current_source)
        self.build_package_button.clicked.connect(self.build_current_package)
        self.go_to_output_folder_button.clicked.connect(self.open_output_folder)
        self.use_support_button.clicked.connect(self.apply_support_to_selected_row)
        self.mark_row_reviewed_button.clicked.connect(self.mark_selected_row_reviewed)
        self.mark_issue_reviewed_button.clicked.connect(self.mark_selected_issue_reviewed)
        self.pose_browse_source_button.clicked.connect(self._browse_pose_source)
        self.pose_browse_output_button.clicked.connect(self._browse_pose_output)
        self.pose_open_output_button.clicked.connect(self.open_pose_output_folder)
        self.pose_convert_button.clicked.connect(self.build_pose_converter_package)
        self.pose_source_edit.returnPressed.connect(self._pose_source_entered)
        self.pose_store_combo.currentTextChanged.connect(self._pose_store_changed)
        self.table_view.selectionModel().currentRowChanged.connect(
            lambda current, previous: self.show_row_details(current.row())
        )

    def _browse_source(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Product Folder")
        if folder:
            self.set_source_path(Path(folder))
            self.analyze_current_source()

    def set_pose_source_path(self, path: Path) -> None:
        source = Path(path)
        self.pose_source_edit.setText(str(source))
        if not self.pose_output_edit.text().strip():
            self.pose_output_edit.setText(str(self._package_output_folder(source)))
        if not self.pose_product_name_edit.text().strip():
            self.pose_product_name_edit.setText(_converted_pose_product_name(source))

    def _pose_source_entered(self) -> None:
        source_text = self.pose_source_edit.text().strip()
        if source_text:
            self.set_pose_source_path(Path(source_text))

    def _browse_pose_source(self) -> None:
        file_name, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select Pose Product Zip",
            "",
            "DIM Zip (*.zip);;All Files (*.*)",
        )
        if file_name:
            self.set_pose_source_path(Path(file_name))

    def _browse_pose_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Pose Converter Output Folder")
        if folder:
            self.pose_output_edit.setText(folder)

    def build_pose_converter_package(self) -> None:
        if self._analyzing:
            return
        source_text = self.pose_source_edit.text().strip()
        if not source_text:
            self._set_pose_status("No pose product selected.")
            return
        source = Path(source_text)
        output = Path(self.pose_output_edit.text().strip()) if self.pose_output_edit.text().strip() else self._package_output_folder(source)
        self.pose_output_edit.setText(str(output))
        try:
            self._save_pose_store_to_catalog()
            self._set_pose_status("Converting pose product...")
            result = self.pose_package_builder(source, output, metadata=self._pose_package_metadata())
        except Exception as exc:
            self._set_pose_status(f"Pose conversion failed: {exc}")
            self._analysis_progress(f"Pose conversion failed: {exc}")
            return
        converted = getattr(result.conversion_report, "converted_count", 0)
        skipped = getattr(result.conversion_report, "skipped_count", 0)
        zip_path = getattr(result.package, "zip_path", "")
        self._set_pose_status(
            f"Converted {converted} pose file(s).\n"
            f"Skipped {skipped} file(s).\n"
            f"Package built: {zip_path}"
        )
        self._analysis_progress(f"Pose package built: {zip_path}")

    def open_pose_output_folder(self) -> None:
        source_text = self.pose_source_edit.text().strip()
        output_text = self.pose_output_edit.text().strip()
        if output_text:
            output_folder = Path(output_text)
        elif source_text:
            output_folder = self._package_output_folder(Path(source_text))
            self.pose_output_edit.setText(str(output_folder))
        else:
            self._set_pose_status("No output folder selected.")
            return
        output_folder.mkdir(parents=True, exist_ok=True)
        self.output_folder_opener(output_folder)

    def _pose_store_changed(self, store_name: str) -> None:
        store = self._matching_store(store_name)
        if store is None:
            return
        self.pose_store_prefix_edit.setText(store.dim_prefix)
        if not self.pose_store_code_edit.text().strip():
            self.pose_store_code_edit.setText(store.default_code)

    def _pose_package_metadata(self) -> dict[str, Any]:
        store_name = self.pose_store_combo.currentText().strip()
        matching_store = self._matching_store(store_name)
        artists = _split_product_artists(self.pose_artists_edit.text())
        return {
            "product_name": self.pose_product_name_edit.text().strip(),
            "store_display_name": store_name,
            "store_id": matching_store.store_id if matching_store is not None else store_name,
            "store_prefix": self.pose_store_prefix_edit.text().strip(),
            "store_code": self.pose_store_code_edit.text().strip(),
            "product_token": self.pose_token_edit.text().strip(),
            "global_id": self.pose_guid_edit.text().strip(),
            "artists": artists,
            "primary_artist": artists[0] if artists else "",
        }

    def _save_pose_store_to_catalog(self) -> None:
        store_name = self.pose_store_combo.currentText().strip()
        if not store_name:
            return
        store = StoreSettings(
            display_name=store_name,
            store_id=self._pose_package_metadata()["store_id"],
            dim_prefix=self.pose_store_prefix_edit.text().strip(),
            default_code=self.pose_store_code_edit.text().strip(),
        )
        upsert_store(self.store_catalog_path, store)
        self.store_catalog = list(load_store_catalog(self.store_catalog_path))

    def _set_pose_status(self, message: str) -> None:
        self.pose_status_text.setPlainText(message)

    def apply_model_to_selected_row(self) -> None:
        if self.table_model.apply_model_to_row(self.table_view.currentIndex().row()):
            self._after_warning_resolution()

    def build_current_package(self) -> None:
        if self._analyzing:
            return
        if self.current_contract.get("hard_blockers"):
            self._set_issue_lines(self._issue_lines() + ["Package build blocked: resolve hard blockers first."])
            return
        source_text = self.source_edit.text().strip()
        if not source_text:
            self._set_issue_lines(["No source selected."])
            return
        try:
            self._save_current_store_to_catalog()
            result = build_dim_package(
                scan_source(Path(source_text)),
                self.current_contract,
                self._package_output_folder(Path(source_text)),
            )
        except Exception as exc:
            self._set_issue_lines([f"Package build failed: {exc}"])
            self._analysis_progress(f"Package build failed: {exc}")
            return
        self._analysis_progress(f"Package built: {result.zip_path}")

    def open_output_folder(self) -> None:
        source_text = self.source_edit.text().strip()
        if not source_text:
            self._set_issue_lines(["No source selected."])
            return
        output_folder = self._package_output_folder(Path(source_text))
        output_folder.mkdir(parents=True, exist_ok=True)
        self.output_folder_opener(output_folder)

    def generate_product_guid(self) -> None:
        self.guid_edit.setText(str(uuid4()))

    def choose_product_image(self) -> None:
        file_name, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select Product Image",
            "",
            "Images (*.jpg *.jpeg *.png)",
        )
        if file_name:
            self.set_product_image_path(Path(file_name))

    def set_product_image_path(self, path: Path) -> None:
        self._set_product_image_text(str(path))
        product = self.current_contract.setdefault("product", {})
        product["product_image"] = self.product_image_path_edit.text().strip()

    def ask_model_for_current_source(self) -> None:
        if self._analyzing:
            return
        source_text = self.source_edit.text().strip()
        if not source_text:
            self._set_issue_lines(["No source selected."])
            return
        try:
            provider = self._selected_model_provider()
        except Exception as exc:
            self._set_issue_lines([f"Model analysis failed: {exc}"])
            return
        if provider is None:
            self._set_issue_lines(["Model provider is off."])
            return
        source = Path(source_text)
        if self.run_analysis_synchronously:
            self._run_analysis_synchronously(source, provider, show_deterministic=False)
        else:
            self._start_analysis(source, provider, show_deterministic=False)

    def _issue_lines(self) -> list[str]:
        product_warnings = self._product_warning_issues()
        row_warnings = [
            {"code": "row-warning", "message": message}
            for message in self.table_model.row_warning_messages()
        ]
        warnings = [
            issue for issue in product_warnings + row_warnings
            if issue.get("message", "") not in self.reviewed_issue_messages
        ]
        blockers = self.current_contract.get("hard_blockers", [])
        lines = [f"Hard blockers: {len(blockers)}", f"Warnings: {len(warnings)}"]
        for issue in blockers + warnings:
            message = issue.get("message", "")
            code = issue.get("code", "issue")
            lines.append(f"{code}: {message}")
        return lines

    def _set_issue_lines(self, lines: list[str]) -> None:
        self.issue_list.clear()
        for line in lines:
            item = QListWidgetItem(line)
            if ": " in line:
                item.setData(Qt.ItemDataRole.UserRole, line.split(": ", 1)[1])
            self.issue_list.addItem(item)

    def _apply_filter(self) -> None:
        self.table_model.set_filter_text(self.filter_edit.text())
        self.table_model.set_warnings_only(self.warnings_only_checkbox.isChecked())
        self.summary_label.setText(self.summary_text())
        self.show_row_details(0 if self.table_model.rowCount() else -1)
        self._set_issue_lines(self._issue_lines())
        self.table_view.resizeColumnsToContents()

    def _provider_changed(self, provider_name: str) -> None:
        current_model = self.model_name_edit.text().strip()
        if provider_name == "Ollama" and current_model in ("", "qwen/qwen3-4b", "qwen/qwen3-32b"):
            self.model_name_edit.setText("qwen3:4b")
        elif provider_name == "LM Studio" and current_model in ("", "qwen3:4b", "qwen3:8b"):
            self.model_name_edit.setText("qwen/qwen3-4b")
        self._update_model_controls()

    def _update_model_controls(self) -> None:
        can_use_model = self.provider_combo.currentText() != "Off" and not self._analyzing
        self.model_name_edit.setEnabled(can_use_model)
        self.ask_model_button.setEnabled(can_use_model)

    def _selected_model_provider(self) -> MetadataSuggestionProvider | None:
        provider_name = self.provider_combo.currentText()
        if provider_name == "Off":
            return None
        return self.model_provider_factory(
            self._provider_key(provider_name),
            self.model_name_edit.text().strip(),
        )

    def _provider_key(self, provider_name: str) -> str:
        if provider_name == "Ollama":
            return "ollama"
        if provider_name == "LM Studio":
            return "lm-studio"
        return "off"

    def _detect_available_model_providers(self) -> tuple[str, ...]:
        providers = []
        if shutil.which("ollama"):
            providers.append("ollama")
        if shutil.which("lms"):
            providers.append("lm-studio")
        return tuple(providers)

    def _provider_labels(self) -> list[str]:
        labels = []
        if "ollama" in self.available_model_providers:
            labels.append("Ollama")
        if "lm-studio" in self.available_model_providers:
            labels.append("LM Studio")
        labels.append("Off")
        return labels

    def _default_provider_label(self) -> str:
        if "ollama" in self.available_model_providers:
            return "Ollama"
        if "lm-studio" in self.available_model_providers:
            return "LM Studio"
        return "Off"

    def _default_model_name(self, provider_name: str) -> str:
        if provider_name == "Ollama":
            return "qwen3:4b"
        if provider_name == "LM Studio":
            return "qwen/qwen3-4b"
        return ""

    def _default_model_provider_factory(
        self,
        provider_key: str,
        model_name: str,
    ) -> MetadataSuggestionProvider:
        if provider_key == "ollama":
            return OllamaProvider(model=model_name or "qwen3:4b", timeout_seconds=120)
        if provider_key == "lm-studio":
            return LMStudioProvider(model=model_name or "qwen/qwen3-4b", timeout_seconds=120)
        raise ValueError(f"Unknown model provider: {provider_key}")

    def _run_analysis_synchronously(
        self,
        source: Path,
        provider: MetadataSuggestionProvider | None,
        show_deterministic: bool = True,
    ) -> None:
        self._set_analyzing(True)
        try:
            if provider is None:
                contract = analyze_source(source, progress=self._analysis_progress)
            elif show_deterministic:
                contract = analyze_source(source, provider=provider, progress=self._analysis_progress)
            else:
                context = _analyze_source_context(source, progress=self._analysis_progress)
                model_result = _request_model_result(provider, context, progress=self._analysis_progress)
                contract = _build_analysis_payload(context, model_result, progress=self._analysis_progress)
        except Exception as exc:
            self._analysis_failed(str(exc))
            return
        self._analysis_finished(contract)

    def _start_analysis(
        self,
        source: Path,
        provider: MetadataSuggestionProvider | None,
        show_deterministic: bool = True,
    ) -> None:
        self._set_analyzing(True)
        self.summary_label.setText("Analyzing..." if provider is None else "Asking model...")
        self._set_issue_lines(["Analyzing source..." if provider is None else "Asking model..."])
        thread = QThread(self)
        worker = AnalysisWorker(source, provider=provider)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._analysis_progress)
        if show_deterministic:
            worker.deterministic_finished.connect(self._analysis_deterministic_finished)
        worker.finished.connect(self._analysis_finished)
        worker.failed.connect(self._analysis_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._analysis_thread_finished)
        thread.finished.connect(thread.deleteLater)

        self.analysis_thread = thread
        self.analysis_worker = worker
        thread.start()

    def _analysis_deterministic_finished(self, contract: dict[str, Any]) -> None:
        self.set_contract(contract)

    def _analysis_finished(self, contract: dict[str, Any]) -> None:
        if self._should_merge_model_contract(contract):
            self._show_model_suggestions(contract)
        else:
            self.set_contract(contract)
        self._set_analyzing(False)

    def _analysis_failed(self, message: str) -> None:
        self.summary_label.setText("Analysis failed")
        self._set_issue_lines([f"Analysis failed: {message}"])
        self._analysis_progress(f"Analysis failed: {message}")
        self._set_analyzing(False)

    def _analysis_progress(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def _analysis_thread_finished(self) -> None:
        self.analysis_thread = None
        self.analysis_worker = None

    def _set_analyzing(self, analyzing: bool) -> None:
        self._analyzing = analyzing
        self.source_edit.setEnabled(not analyzing)
        self.browse_button.setEnabled(not analyzing)
        self.analyze_button.setEnabled(not analyzing)
        self.provider_combo.setEnabled(not analyzing)
        self.build_package_button.setEnabled(not analyzing)
        self.go_to_output_folder_button.setEnabled(not analyzing)
        self.choose_product_image_button.setEnabled(not analyzing)
        self.pose_source_edit.setEnabled(not analyzing)
        self.pose_browse_source_button.setEnabled(not analyzing)
        self.pose_output_edit.setEnabled(not analyzing)
        self.pose_browse_output_button.setEnabled(not analyzing)
        self.pose_open_output_button.setEnabled(not analyzing)
        self.pose_convert_button.setEnabled(not analyzing)
        self._update_model_controls()

    def _after_warning_resolution(self) -> None:
        self.summary_label.setText(self.summary_text())
        self._set_issue_lines(self._issue_lines())
        self.show_row_details(0 if self.table_model.rowCount() else -1)
        self.table_view.resizeColumnsToContents()

    def _ensure_product_metadata(self) -> None:
        product = self.current_contract.setdefault("product", {})
        source_path = product.get("source_path", "")
        if not product.get("product_name"):
            product["product_name"] = Path(source_path).stem if source_path else ""
        if not product.get("store_display_name"):
            product["store_display_name"] = product.get("store_id") or self.app_settings.default_store.display_name
        matching_store = self._matching_store(str(product.get("store_display_name") or product.get("store_id") or ""))
        if not product.get("store_id"):
            product["store_id"] = matching_store.store_id if matching_store else self.app_settings.default_store.store_id
        if not product.get("store_prefix"):
            product["store_prefix"] = matching_store.dim_prefix if matching_store else self.app_settings.default_store.dim_prefix
        if not product.get("store_code"):
            product["store_code"] = matching_store.default_code if matching_store else self.app_settings.default_store.default_code
        if not product.get("product_token"):
            product["product_token"] = str(self.app_settings.next_product_number)
        if not product.get("global_id"):
            product["global_id"] = str(uuid4())
        artists = [str(artist) for artist in product.get("artists", []) if str(artist)]
        primary_artist = str(product.get("primary_artist", ""))
        if not artists and primary_artist:
            artists = [primary_artist]
            product["artists"] = artists
        if artists and not primary_artist:
            product["primary_artist"] = artists[0]

    def _populate_product_fields(self) -> None:
        product = self.current_contract.get("product", {})
        self._syncing_product_fields = True
        try:
            self.product_name_edit.setText(str(product.get("product_name", "")))
            self.store_combo.setCurrentText(str(product.get("store_display_name", "") or product.get("store_id", "")))
            self.store_prefix_edit.setText(str(product.get("store_prefix", "")))
            self.store_code_edit.setText(str(product.get("store_code", "")))
            self.token_edit.setText(str(product.get("product_token", "")))
            self.guid_edit.setText(str(product.get("global_id", "")))
            self.artists_edit.setText("; ".join(str(artist) for artist in product.get("artists", []) if str(artist)))
            self._set_product_image_text(str(product.get("product_image", "")))
        finally:
            self._syncing_product_fields = False

    def _store_changed(self, store_name: str) -> None:
        if self._syncing_product_fields:
            return
        store = self._matching_store(store_name)
        if store is not None:
            self.store_prefix_edit.setText(store.dim_prefix)
            if not self.store_code_edit.text().strip():
                self.store_code_edit.setText(store.default_code)
        self._product_metadata_changed()

    def _product_metadata_changed(self) -> None:
        if self._syncing_product_fields:
            return
        product = self.current_contract.setdefault("product", {})
        artists = _split_product_artists(self.artists_edit.text())
        store_name = self.store_combo.currentText().strip()
        matching_store = self._matching_store(store_name)
        product["product_name"] = self.product_name_edit.text().strip()
        product["store_display_name"] = store_name
        product["store_id"] = matching_store.store_id if matching_store is not None else store_name
        product["store_prefix"] = self.store_prefix_edit.text().strip()
        product["store_code"] = self.store_code_edit.text().strip()
        product["product_token"] = self.token_edit.text().strip()
        product["global_id"] = self.guid_edit.text().strip()
        product["product_image"] = self.product_image_path_edit.text().strip()
        product["artists"] = artists
        product["primary_artist"] = artists[0] if artists else ""
        self.summary_label.setText(self.summary_text())

    def _set_product_image_text(self, value: str) -> None:
        self.product_image_path_edit.setText(value)
        drop_zone = getattr(self, "product_image_drop_zone", None)
        if drop_zone is not None:
            drop_zone.set_image_path(self._resolved_product_image_path(value))

    def _resolved_product_image_path(self, value: str) -> Path | None:
        if not value:
            return None
        path = Path(value)
        if path.is_absolute():
            return path
        product = self.current_contract.get("product", {})
        source_path = product.get("source_path") or self.source_edit.text().strip()
        if not source_path or product.get("source_kind") == "zip":
            return None
        base = Path(str(source_path))
        content_root = str(product.get("content_root") or "")
        candidate = base / content_root / value if content_root else base / value
        return candidate

    def _package_output_folder(self, source: Path) -> Path:
        configured = self.app_settings.dim_downloads_folder or self.app_settings.default_output_folder
        if configured:
            return Path(configured)
        return source.parent / "Daz Forge Packages"

    def _matching_store(self, value: str) -> StoreSettings | None:
        key = value.strip().lower()
        if not key:
            return None
        for store in self.store_catalog:
            if store.display_name.strip().lower() == key or store.store_id.strip().lower() == key:
                return store
        return None

    def _save_current_store_to_catalog(self) -> None:
        product = self.current_contract.get("product", {})
        store_name = str(product.get("store_display_name") or "").strip()
        if not store_name:
            return
        store = StoreSettings(
            display_name=store_name,
            store_id=str(product.get("store_id") or store_name),
            dim_prefix=str(product.get("store_prefix") or ""),
            default_code=str(product.get("store_code") or ""),
        )
        upsert_store(self.store_catalog_path, store)
        self.store_catalog = list(load_store_catalog(self.store_catalog_path))

    def _should_merge_model_contract(self, contract: dict[str, Any]) -> bool:
        product = contract.get("product", {})
        current_product = self.current_contract.get("product", {})
        return (
            bool(product.get("model_provider"))
            and bool(self.current_contract.get("rows"))
            and current_product.get("source_path") == product.get("source_path")
        )

    def _merge_model_contract(self, model_contract: dict[str, Any]) -> None:
        merged = deepcopy(self.current_contract)
        current_rows = self.table_model.approved_rows()
        model_rows_by_path = {
            row.get("path", ""): row
            for row in model_contract.get("rows", [])
        }
        for row in current_rows:
            model_row = model_rows_by_path.get(row.get("path", ""))
            if model_row is not None:
                row["model"] = deepcopy(model_row.get("model"))
        merged["rows"] = current_rows
        merged["product"] = {
            **merged.get("product", {}),
            "model_provider": model_contract.get("product", {}).get("model_provider", ""),
            "model_available": model_contract.get("product", {}).get("model_available", False),
        }
        current_warnings = [
            warning for warning in merged.get("warnings", [])
            if warning.get("code") != "model-warning"
        ]
        model_warnings = [
            warning for warning in model_contract.get("warnings", [])
            if warning.get("code") == "model-warning"
        ]
        merged["warnings"] = current_warnings + model_warnings

        self.current_contract = merged
        self.table_model.set_contract(merged)
        self.summary_label.setText(self.summary_text())
        self._set_issue_lines(self._issue_lines())
        self.table_view.resizeColumnsToContents()
        self.show_row_details(0 if self.table_model.rowCount() else -1)

    def _show_model_suggestions(self, model_contract: dict[str, Any]) -> None:
        diffs = _model_suggestion_diffs(self.current_contract, model_contract)
        self._merge_model_contract(model_contract)
        if not diffs:
            self._analysis_progress("Model finished: no suggested changes")
            return
        dialog = ModelSuggestionDialog(diffs, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected_diffs = dialog.selected_diffs()
        if not selected_diffs:
            return
        self.set_contract(_apply_model_suggestion_diffs(self.current_contract, selected_diffs))
        self._analysis_progress(f"Applied {len(selected_diffs)} model suggestion(s)")

    def _product_warning_issues(self) -> list[dict[str, str]]:
        row_warning_messages = set()
        for row in self.current_contract.get("rows", []):
            path = row.get("path", "")
            file_name = path.rsplit("/", 1)[-1]
            for warning in row.get("warnings", []):
                row_warning_messages.add(f"{path}: {warning}")
                row_warning_messages.add(f"{file_name}: {warning}")
        product_issues = []
        for issue in self.current_contract.get("warnings", []):
            message = issue.get("message", "")
            if message not in row_warning_messages:
                product_issues.append(issue)
        return product_issues

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #202124;
                color: #e8eaed;
                font-size: 12px;
            }
            QLineEdit, QTextEdit {
                background: #2b2c30;
                border: 1px solid #46484f;
                border-radius: 6px;
                padding: 8px 10px;
                selection-background-color: #16c4a0;
            }
            QLineEdit[tableEditor="true"], QComboBox[tableEditor="true"] {
                background: #2b2c30;
                border: 1px solid #46484f;
                border-radius: 3px;
                padding: 0 4px;
                min-height: 20px;
                selection-background-color: #16c4a0;
            }
            QPushButton {
                background: #30343a;
                border: 1px solid #555b64;
                border-radius: 6px;
                padding: 8px 14px;
            }
            QPushButton:hover {
                background: #3a3f47;
            }
            QPushButton#primaryBuildPackageButton {
                background: #139a7f;
                border-color: #20c8a7;
                color: #ffffff;
                font-weight: 600;
            }
            QPushButton#primaryBuildPackageButton:hover, QPushButton#primaryPoseConvertButton:hover {
                background: #17b597;
            }
            QPushButton#primaryBuildPackageButton:disabled, QPushButton#primaryPoseConvertButton:disabled {
                background: #2f4f49;
                border-color: #45645e;
                color: #aeb8b5;
            }
            QPushButton#primaryPoseConvertButton {
                background: #139a7f;
                border-color: #20c8a7;
                color: #ffffff;
                font-weight: 600;
            }
            QTableView, QListWidget, QTextEdit {
                background: #25262a;
                alternate-background-color: #2c2d32;
                border: 1px solid #3f4249;
                gridline-color: #3b3d43;
                selection-background-color: #12b892;
                selection-color: #101214;
            }
            QCheckBox {
                spacing: 8px;
                padding: 4px;
            }
            QHeaderView::section {
                background: #30323a;
                color: #e8eaed;
                border: 0;
                border-right: 1px solid #46484f;
                padding: 7px;
            }
            QLabel {
                color: #d7dadf;
                padding: 2px 0;
            }
            QLabel[imageDropZone="true"] {
                background: #25262a;
                border: 1px dashed #555b64;
                border-radius: 6px;
                color: #aeb4bd;
                padding: 16px;
            }
            QTabWidget::pane {
                border: 1px solid #3f4249;
                border-radius: 6px;
                top: -1px;
            }
            QTabBar::tab {
                background: #2a2d33;
                border: 1px solid #3f4249;
                border-bottom: 0;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                color: #c9cdd4;
                padding: 8px 18px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #202124;
                color: #ffffff;
                border-color: #4e535c;
            }
            """
        )


def analyze_source(
    source: Path,
    provider: MetadataSuggestionProvider | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    context = _analyze_source_context(source, progress=progress)
    model_result = None
    if provider is not None:
        model_result = _request_model_result(provider, context, progress=progress)
    return _build_analysis_payload(context, model_result, progress=progress)


def _analyze_source_context(
    source: Path,
    progress: Callable[[str], None] | None = None,
) -> AnalysisContext:
    _report_progress(progress, "Scanning source...")
    scan = scan_source(source)
    total_files = len(scan.files)
    _report_progress(progress, f"Scanned {total_files} files")
    _report_progress(progress, f"Classifying files... {total_files} / {total_files}")
    inventory = classify_inventory(scan)
    smart_content_count = len(inventory.smart_content)
    _report_progress(progress, f"Inferring metadata... {smart_content_count} / {smart_content_count}")
    inference = infer_metadata(scan, inventory)
    return AnalysisContext(scan=scan, inventory=inventory, inference=inference)


def _request_model_result(
    provider: MetadataSuggestionProvider,
    context: AnalysisContext,
    progress: Callable[[str], None] | None = None,
) -> ModelSuggestionResult:
    smart_content_count = len(context.inventory.smart_content)
    _report_progress(
        progress,
        f"Asking {_provider_progress_label(provider)}... {smart_content_count} / {smart_content_count}",
    )
    return request_model_suggestions(provider, build_model_packet(context.inference))


def _build_analysis_payload(
    context: AnalysisContext,
    model_result: ModelSuggestionResult | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    _report_progress(progress, "Building review grid...")
    contract = build_review_contract(context.scan, context.inventory, context.inference, model_result)
    payload = contract_to_dict(contract)
    _report_progress(progress, _ready_status(payload))
    return payload


def _report_progress(progress: Callable[[str], None] | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _provider_progress_label(provider: MetadataSuggestionProvider) -> str:
    name = str(getattr(provider, "name", "model")).strip() or "model"
    model = str(getattr(provider, "model", "")).strip()
    timeout_seconds = getattr(provider, "timeout_seconds", None)
    display_names = {
        "lm-studio": "LM Studio",
        "ollama": "Ollama",
    }
    parts = [display_names.get(name, name)]
    if model:
        parts.append(model)
    if timeout_seconds:
        parts.append(f"(up to {timeout_seconds}s)")
    return " ".join(parts)


def _model_suggestion_diffs(
    current_contract: dict[str, Any],
    model_contract: dict[str, Any],
) -> list[dict[str, Any]]:
    current_rows_by_path = {
        row.get("path", ""): row
        for row in current_contract.get("rows", [])
    }
    diffs: list[dict[str, Any]] = []
    for model_row in model_contract.get("rows", []):
        path = model_row.get("path", "")
        current_row = current_rows_by_path.get(path)
        model_fields = model_row.get("model")
        if current_row is None or not model_fields:
            continue
        final_fields = current_row.get("final", {})
        for field in ("content_type", "categories", "compatibility_base", "compatibilities"):
            current_value = _metadata_value(final_fields, field)
            suggested_value = _metadata_value(model_fields, field)
            if not _has_suggestion_value(suggested_value):
                continue
            if current_value != suggested_value:
                diffs.append(
                    _harden_model_diff(
                        {
                            "path": path,
                            "field": field,
                            "current": current_value,
                            "suggested": suggested_value,
                        }
                    )
                )

    return diffs


def _harden_model_diff(diff: dict[str, Any]) -> dict[str, Any]:
    reasons = _model_diff_risk_reasons(diff)
    if reasons:
        return {
            **diff,
            "risk": "blocked",
            "risk_reasons": reasons,
        }
    return diff


def _model_diff_risk_reasons(diff: dict[str, Any]) -> list[str]:
    path = str(diff.get("path", "")).lower().replace("\\", "/")
    field = str(diff.get("field", ""))
    current = diff.get("current")
    suggested = diff.get("suggested")
    reasons: list[str] = []
    if field == "categories":
        suggested_categories = _lower_list(suggested)
        if _path_contains_segment(path, "clothing") and any(
            category.startswith("/default/scenes") for category in suggested_categories
        ):
            reasons.append("category conflicts with clothing path")
        if _path_contains_segment(path, "materials") and any(
            category.startswith("/default/shaders") for category in suggested_categories
        ):
            reasons.append("category conflicts with materials path")
    if field == "compatibility_base":
        current_text = str(current or "").strip()
        suggested_text = str(suggested or "").strip()
        if not current_text and suggested_text:
            reasons.append("model added compatibility base")
        elif (
            current_text
            and suggested_text
            and current_text != suggested_text
            and _normalize_compatibility_base(current_text) == _normalize_compatibility_base(suggested_text)
        ):
            reasons.append("model shortened compatibility base")
    return reasons


def _path_contains_segment(path: str, segment: str) -> bool:
    return f"/{segment}/" in f"/{path}/"


def _lower_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).lower() for item in value if str(item)]
    text = str(value or "")
    return [text.lower()] if text else []


def _normalize_compatibility_base(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if normalized.lower().endswith("/base"):
        normalized = normalized[:-5]
    return normalized.lower()


def _is_blocked_model_diff(diff: dict[str, Any]) -> bool:
    return diff.get("risk") == "blocked"


def _apply_model_suggestion_diffs(
    contract: dict[str, Any],
    diffs: list[dict[str, Any]],
) -> dict[str, Any]:
    updated = deepcopy(contract)
    rows_by_path = {
        row.get("path", ""): row
        for row in updated.get("rows", [])
    }
    for diff in diffs:
        if _is_blocked_model_diff(diff):
            continue
        row = rows_by_path.get(diff.get("path", ""))
        if row is None:
            continue
        final = row.setdefault("final", {})
        final[str(diff.get("field", ""))] = deepcopy(diff.get("suggested"))
    return updated


def _metadata_value(fields: dict[str, Any], field: str) -> Any:
    value = fields.get(field, [] if field in {"categories", "compatibilities"} else "")
    if field in {"categories", "compatibilities"}:
        if isinstance(value, str):
            return [value] if value else []
        return [str(item) for item in value if str(item)]
    return str(value)


def _has_suggestion_value(value: Any) -> bool:
    if isinstance(value, list):
        return bool(value)
    return bool(str(value))


def _model_diff_label(diff: dict[str, Any]) -> str:
    prefix = ""
    if _is_blocked_model_diff(diff):
        prefix = f"BLOCKED ({'; '.join(diff.get('risk_reasons', []))}) | "
    return (
        f"{prefix}{diff.get('path', '')} | "
        f"{_field_label(str(diff.get('field', '')))}: "
        f"{_display_diff_value(diff.get('current'))} -> {_display_diff_value(diff.get('suggested'))}"
    )


def _field_label(field: str) -> str:
    return {
        "content_type": "Content Type",
        "categories": "Category",
        "compatibility_base": "Compatibility Base",
        "compatibilities": "Compatibilities",
    }.get(field, field)


def _display_diff_value(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value) or "-"
    return str(value) or "-"


def _split_product_artists(value: str) -> list[str]:
    normalized = value.replace("\n", ";").replace(",", ";")
    return [part.strip() for part in normalized.split(";") if part.strip()]


def _converted_pose_product_name(source: Path) -> str:
    name = source.stem
    name = re.sub(r"^[A-Z]{0,6}\d{8}-\d{2}_", "", name)
    replacements = (
        ("Genesis8Female", "Genesis9"),
        ("Genesis 8 Female", "Genesis 9"),
        ("G8F", "G9"),
    )
    for old, new in replacements:
        name = name.replace(old, new)
    return name or "Converted Pose Product"


def _default_store_catalog_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "stores.json"


def _open_folder_with_desktop(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def _ready_status(contract: dict[str, Any]) -> str:
    rows = len(contract.get("rows", []))
    blockers = len(contract.get("hard_blockers", []))
    warnings = len(contract.get("warnings", []))
    return f"Ready: {rows} rows, {blockers} blockers, {warnings} warnings"
