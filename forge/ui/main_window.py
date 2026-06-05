from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from forge.analyzer.inference import infer_metadata
from forge.analyzer.inventory import classify_inventory
from forge.analyzer.review_contract import build_review_contract, contract_to_dict
from forge.analyzer.source import scan_source
from forge.ui.review_model import ReviewTableModel


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Daz Forge")
        self.resize(1320, 780)
        self.setAcceptDrops(True)

        self.current_contract: dict[str, Any] = {"rows": [], "warnings": [], "hard_blockers": []}
        self.table_model = ReviewTableModel(self.current_contract)

        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Select a product folder or zip")
        self.browse_button = QPushButton("Browse")
        self.analyze_button = QPushButton("Analyze")
        self.summary_label = QLabel("No source analyzed")
        self.summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.issue_list = QListWidget()
        self.table_view = QTableView()
        self.table_view.setModel(self.table_model)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSortingEnabled(False)
        self.table_view.setWordWrap(False)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.verticalHeader().setDefaultSectionSize(28)

        self._build_layout()
        self._connect_signals()
        self._apply_style()

    def set_source_path(self, path: Path) -> None:
        self.source_edit.setText(str(path))

    def analyze_current_source(self) -> None:
        source_text = self.source_edit.text().strip()
        if not source_text:
            self._set_issue_lines(["No source selected."])
            return
        try:
            contract = analyze_source(Path(source_text))
        except Exception as exc:
            self._set_issue_lines([f"Analysis failed: {exc}"])
            return
        self.set_contract(contract)

    def set_contract(self, contract: dict[str, Any]) -> None:
        self.current_contract = contract
        self.table_model.set_contract(contract)
        self.summary_label.setText(self.summary_text())
        self._set_issue_lines(self._issue_lines())
        self.table_view.resizeColumnsToContents()

    def summary_text(self) -> str:
        product = self.current_contract.get("product", {})
        if not product:
            return "No source analyzed"
        artists = ", ".join(product.get("artists", [])) or "-"
        return (
            f"Type: {product.get('product_type', '-')}    "
            f"Artist: {product.get('primary_artist') or artists}    "
            f"Rows: {product.get('smart_content_count', 0)}    "
            f"Files: {product.get('total_files', 0)}    "
            f"Model: {product.get('model_provider') or 'off'}"
        )

    def issue_text(self) -> str:
        return "\n".join(self._issue_lines())

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
        splitter.addWidget(self.table_view)
        self.issue_list.setMinimumHeight(120)
        self.issue_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        splitter.addWidget(self.issue_list)
        splitter.setSizes([560, 140])
        layout.addWidget(splitter, 1)

    def _connect_signals(self) -> None:
        self.browse_button.clicked.connect(self._browse_source)
        self.analyze_button.clicked.connect(self.analyze_current_source)
        self.source_edit.returnPressed.connect(self.analyze_current_source)

    def _browse_source(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Product Folder")
        if folder:
            self.set_source_path(Path(folder))
            self.analyze_current_source()

    def _issue_lines(self) -> list[str]:
        warnings = self.current_contract.get("warnings", [])
        blockers = self.current_contract.get("hard_blockers", [])
        lines = [f"Hard blockers: {len(blockers)}", f"Warnings: {len(warnings)}"]
        for issue in blockers + warnings:
            message = issue.get("message", "")
            code = issue.get("code", "issue")
            lines.append(f"{code}: {message}")
        return lines

    def _set_issue_lines(self, lines: list[str]) -> None:
        self.issue_list.clear()
        self.issue_list.addItems(lines)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #202124;
                color: #e8eaed;
                font-size: 12px;
            }
            QLineEdit {
                background: #2b2c30;
                border: 1px solid #46484f;
                border-radius: 6px;
                padding: 8px 10px;
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
            QTableView, QListWidget {
                background: #25262a;
                alternate-background-color: #2c2d32;
                border: 1px solid #3f4249;
                gridline-color: #3b3d43;
                selection-background-color: #12b892;
                selection-color: #101214;
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


def analyze_source(source: Path) -> dict[str, Any]:
    scan = scan_source(source)
    inventory = classify_inventory(scan)
    inference = infer_metadata(scan, inventory)
    contract = build_review_contract(scan, inventory, inference)
    return contract_to_dict(contract)
