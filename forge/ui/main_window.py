from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
from forge.analyzer.inventory import classify_inventory
from forge.analyzer.model_provider import (
    LMStudioProvider,
    MetadataSuggestionProvider,
    OllamaProvider,
    build_model_packet,
    request_model_suggestions,
)
from forge.analyzer.review_contract import build_review_contract, contract_to_dict
from forge.analyzer.source import scan_source
from forge.ui.delegates import CONTENT_TYPE_OPTIONS, CompactLineEditDelegate, SearchableComboDelegate
from forge.ui.review_model import ReviewTableModel


class AnalysisWorker(QObject):
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, source: Path, provider: MetadataSuggestionProvider | None = None) -> None:
        super().__init__()
        self.source = source
        self.provider = provider

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(analyze_source(self.source, provider=self.provider))
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(
        self,
        model_provider_factory: Callable[[str, str], MetadataSuggestionProvider] | None = None,
        available_model_providers: tuple[str, ...] | None = None,
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
        self.analyze_button = QPushButton("Analyze")
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter rows")
        self.warnings_only_checkbox = QCheckBox("Warnings only")
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(self._provider_labels())
        self.provider_combo.setCurrentText(self._default_provider_label())
        self.model_name_edit = QLineEdit(self._default_model_name(self.provider_combo.currentText()))
        self.model_name_edit.setPlaceholderText("Model")
        self.model_name_edit.setMinimumWidth(220)
        self.use_model_button = QPushButton("Use Model")
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
        try:
            provider = self._selected_model_provider()
        except Exception as exc:
            self._set_issue_lines([f"Analysis failed: {exc}"])
            return
        source = Path(source_text)
        if self.run_analysis_synchronously:
            self._run_analysis_synchronously(source, provider)
        else:
            self._start_analysis(source, provider)

    def set_contract(self, contract: dict[str, Any]) -> None:
        self.current_contract = contract
        self.reviewed_issue_messages = set()
        self.table_model.set_contract(contract)
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
        source_bar.addWidget(self.analyze_button)
        layout.addLayout(source_bar)

        layout.addWidget(self.summary_label)

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
        model_bar.addWidget(self.use_model_button)
        detail_layout.addLayout(model_bar)
        action_bar = QHBoxLayout()
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
        self.analyze_button.clicked.connect(self.analyze_current_source)
        self.source_edit.returnPressed.connect(self.analyze_current_source)
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.warnings_only_checkbox.toggled.connect(self._apply_filter)
        self.provider_combo.currentTextChanged.connect(self._provider_changed)
        self.use_model_button.clicked.connect(self.apply_model_to_selected_row)
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
        self.use_model_button.setEnabled(can_use_model)

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
    ) -> None:
        self._set_analyzing(True)
        try:
            contract = analyze_source(source, provider=provider)
        except Exception as exc:
            self._analysis_failed(str(exc))
            return
        self._analysis_finished(contract)

    def _start_analysis(self, source: Path, provider: MetadataSuggestionProvider | None) -> None:
        self._set_analyzing(True)
        self.summary_label.setText("Analyzing...")
        self._set_issue_lines(["Analyzing source..."])
        thread = QThread(self)
        worker = AnalysisWorker(source, provider=provider)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
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

    def _analysis_finished(self, contract: dict[str, Any]) -> None:
        self.set_contract(contract)
        self._set_analyzing(False)

    def _analysis_failed(self, message: str) -> None:
        self.summary_label.setText("Analysis failed")
        self._set_issue_lines([f"Analysis failed: {message}"])
        self._set_analyzing(False)

    def _analysis_thread_finished(self) -> None:
        self.analysis_thread = None
        self.analysis_worker = None

    def _set_analyzing(self, analyzing: bool) -> None:
        self._analyzing = analyzing
        self.source_edit.setEnabled(not analyzing)
        self.browse_button.setEnabled(not analyzing)
        self.analyze_button.setEnabled(not analyzing)
        self.provider_combo.setEnabled(not analyzing)
        self.analyze_button.setText("Analyzing..." if analyzing else "Analyze")
        self._update_model_controls()

    def _after_warning_resolution(self) -> None:
        self.summary_label.setText(self.summary_text())
        self._set_issue_lines(self._issue_lines())
        self.show_row_details(0 if self.table_model.rowCount() else -1)
        self.table_view.resizeColumnsToContents()

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
) -> dict[str, Any]:
    scan = scan_source(source)
    inventory = classify_inventory(scan)
    inference = infer_metadata(scan, inventory)
    model_result = None
    if provider is not None:
        model_result = request_model_suggestions(provider, build_model_packet(inference))
    contract = build_review_contract(scan, inventory, inference, model_result)
    return contract_to_dict(contract)
