from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any, Callable
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableView,
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
from forge.settings import AppSettings
from forge.ui.delegates import CONTENT_TYPE_OPTIONS, CompactLineEditDelegate, SearchableComboDelegate
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
        run_analysis_synchronously: bool = False,
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
        self._syncing_product_fields = False
        self.current_contract: dict[str, Any] = {"rows": [], "warnings": [], "hard_blockers": []}
        self.table_model = ReviewTableModel(self.current_contract)
        self.model_provider_factory = model_provider_factory or self._default_model_provider_factory
        self.available_model_providers = (
            available_model_providers
            if available_model_providers is not None
            else self._detect_available_model_providers()
        )

        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Select a product folder or zip")
        self.browse_button = QPushButton("Browse")
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter rows")
        self.warnings_only_checkbox = QCheckBox("Warnings only")
        self.product_name_edit = QLineEdit()
        self.product_name_edit.setPlaceholderText("Product name")
        self.store_edit = QLineEdit()
        self.store_edit.setPlaceholderText("Store")
        self.store_code_edit = QLineEdit()
        self.store_code_edit.setPlaceholderText("Store code")
        self.token_edit = QLineEdit()
        self.token_edit.setPlaceholderText("Token")
        self.guid_edit = QLineEdit()
        self.guid_edit.setPlaceholderText("GUID")
        self.generate_guid_button = QPushButton("Generate")
        self.artists_edit = QLineEdit()
        self.artists_edit.setPlaceholderText("Artists")
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(self._provider_labels())
        self.provider_combo.setCurrentText(self._default_provider_label())
        self.model_name_edit = QLineEdit(self._default_model_name(self.provider_combo.currentText()))
        self.model_name_edit.setPlaceholderText("Model")
        self.model_name_edit.setMinimumWidth(220)
        self.ask_model_button = QPushButton("Ask Model")
        self.build_package_button = QPushButton("Build Package")
        self.use_support_button = QPushButton("Use Support")
        self.mark_row_reviewed_button = QPushButton("Mark Row Reviewed")
        self.mark_issue_reviewed_button = QPushButton("Mark Issue Reviewed")
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
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        source_bar = QHBoxLayout()
        source_bar.addWidget(self.source_edit, 1)
        source_bar.addWidget(self.browse_button)
        layout.addLayout(source_bar)

        layout.addWidget(self.summary_label)

        product_bar = QHBoxLayout()
        product_bar.addWidget(QLabel("Product"))
        product_bar.addWidget(self.product_name_edit, 2)
        product_bar.addWidget(QLabel("Store"))
        product_bar.addWidget(self.store_edit, 1)
        product_bar.addWidget(QLabel("Code"))
        product_bar.addWidget(self.store_code_edit)
        product_bar.addWidget(QLabel("Token"))
        product_bar.addWidget(self.token_edit)
        product_bar.addWidget(QLabel("GUID"))
        product_bar.addWidget(self.guid_edit, 2)
        product_bar.addWidget(self.generate_guid_button)
        product_bar.addWidget(QLabel("Artists"))
        product_bar.addWidget(self.artists_edit, 2)
        layout.addLayout(product_bar)

        splitter = QSplitter(Qt.Orientation.Vertical)
        review_splitter = QSplitter(Qt.Orientation.Horizontal)
        grid_container = QWidget()
        grid_layout = QVBoxLayout(grid_container)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(8)
        filter_bar = QHBoxLayout()
        filter_bar.addWidget(self.filter_edit, 1)
        filter_bar.addWidget(self.warnings_only_checkbox)
        grid_layout.addLayout(filter_bar)
        grid_layout.addWidget(self.table_view, 1)
        review_splitter.addWidget(grid_container)

        self.detail_view.setMinimumWidth(340)
        detail_container = QWidget()
        detail_layout = QVBoxLayout(detail_container)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(8)
        model_bar = QHBoxLayout()
        model_bar.addWidget(self.provider_combo)
        model_bar.addWidget(self.model_name_edit, 1)
        model_bar.addWidget(self.ask_model_button)
        detail_layout.addLayout(model_bar)
        action_bar = QHBoxLayout()
        action_bar.addWidget(self.build_package_button)
        action_bar.addWidget(self.use_support_button)
        action_bar.addWidget(self.mark_row_reviewed_button)
        detail_layout.addLayout(action_bar)
        detail_layout.addWidget(self.detail_view, 1)
        review_splitter.addWidget(detail_container)
        review_splitter.setSizes([900, 360])
        splitter.addWidget(review_splitter)
        self.issue_list.setMinimumHeight(120)
        self.issue_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        issue_container = QWidget()
        issue_layout = QVBoxLayout(issue_container)
        issue_layout.setContentsMargins(0, 0, 0, 0)
        issue_layout.setSpacing(8)
        issue_layout.addWidget(self.issue_list)
        issue_layout.addWidget(self.mark_issue_reviewed_button)
        splitter.addWidget(issue_container)
        splitter.setSizes([560, 140])
        layout.addWidget(splitter, 1)

    def _connect_signals(self) -> None:
        self.browse_button.clicked.connect(self._browse_source)
        self.source_edit.returnPressed.connect(self.analyze_current_source)
        for product_field in (
            self.product_name_edit,
            self.store_edit,
            self.store_code_edit,
            self.token_edit,
            self.guid_edit,
            self.artists_edit,
        ):
            product_field.textChanged.connect(self._product_metadata_changed)
        self.generate_guid_button.clicked.connect(self.generate_product_guid)
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.warnings_only_checkbox.toggled.connect(self._apply_filter)
        self.provider_combo.currentTextChanged.connect(self._provider_changed)
        self.ask_model_button.clicked.connect(self.ask_model_for_current_source)
        self.build_package_button.clicked.connect(self.build_current_package)
        self.use_support_button.clicked.connect(self.apply_support_to_selected_row)
        self.mark_row_reviewed_button.clicked.connect(self.mark_selected_row_reviewed)
        self.mark_issue_reviewed_button.clicked.connect(self.mark_selected_issue_reviewed)
        self.table_view.selectionModel().currentRowChanged.connect(
            lambda current, previous: self.show_row_details(current.row())
        )

    def _browse_source(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Product Folder")
        if folder:
            self.set_source_path(Path(folder))
            self.analyze_current_source()

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

    def generate_product_guid(self) -> None:
        self.guid_edit.setText(str(uuid4()))

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
        self.provider_combo.setEnabled(not analyzing)
        self.build_package_button.setEnabled(not analyzing)
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
        if not product.get("store_id"):
            product["store_id"] = self.app_settings.default_store.store_id
        if not product.get("store_code"):
            product["store_code"] = self.app_settings.default_store.dim_prefix
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
            self.store_edit.setText(str(product.get("store_display_name", "")))
            self.store_code_edit.setText(str(product.get("store_code") or product.get("store_id", "")))
            self.token_edit.setText(str(product.get("product_token", "")))
            self.guid_edit.setText(str(product.get("global_id", "")))
            self.artists_edit.setText("; ".join(str(artist) for artist in product.get("artists", []) if str(artist)))
        finally:
            self._syncing_product_fields = False

    def _product_metadata_changed(self) -> None:
        if self._syncing_product_fields:
            return
        product = self.current_contract.setdefault("product", {})
        artists = _split_product_artists(self.artists_edit.text())
        product["product_name"] = self.product_name_edit.text().strip()
        product["store_display_name"] = self.store_edit.text().strip()
        product["store_id"] = self.store_code_edit.text().strip()
        product["store_code"] = self.store_code_edit.text().strip()
        product["product_token"] = self.token_edit.text().strip()
        product["global_id"] = self.guid_edit.text().strip()
        product["artists"] = artists
        product["primary_artist"] = artists[0] if artists else ""
        self.summary_label.setText(self.summary_text())

    def _package_output_folder(self, source: Path) -> Path:
        configured = self.app_settings.dim_downloads_folder or self.app_settings.default_output_folder
        if configured:
            return Path(configured)
        return source.parent / "Daz Forge Packages"

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
                    {
                        "path": path,
                        "field": field,
                        "current": current_value,
                        "suggested": suggested_value,
                    }
                )
    return diffs


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
    return (
        f"{diff.get('path', '')} | "
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


def _ready_status(contract: dict[str, Any]) -> str:
    rows = len(contract.get("rows", []))
    blockers = len(contract.get("hard_blockers", []))
    warnings = len(contract.get("warnings", []))
    return f"Ready: {rows} rows, {blockers} blockers, {warnings} warnings"
