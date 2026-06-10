from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


class DimPackagerPage(QWidget):
    """Review and package one DAZ product as a DIM zip."""

    def __init__(self, controller: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.detail_layout: QVBoxLayout
        self.package_action_bar: QHBoxLayout
        self._build_layout()

    def _build_layout(self) -> None:
        controller = self.controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        source_bar = QHBoxLayout()
        source_bar.addWidget(controller.source_edit, 1)
        source_bar.addWidget(controller.browse_button)
        layout.addLayout(source_bar)

        layout.addWidget(controller.summary_label)

        product_bar = QHBoxLayout()
        product_bar.addWidget(QLabel("Product"))
        product_bar.addWidget(controller.product_name_edit, 2)
        product_bar.addWidget(QLabel("Store"))
        product_bar.addWidget(controller.store_combo, 1)
        product_bar.addWidget(QLabel("Prefix"))
        product_bar.addWidget(controller.store_prefix_edit)
        product_bar.addWidget(QLabel("Code"))
        product_bar.addWidget(controller.store_code_edit)
        product_bar.addWidget(QLabel("Token"))
        product_bar.addWidget(controller.token_edit)
        product_bar.addWidget(QLabel("GUID"))
        product_bar.addWidget(controller.guid_edit, 2)
        product_bar.addWidget(controller.generate_guid_button)
        product_bar.addWidget(QLabel("Artists"))
        product_bar.addWidget(controller.artists_edit, 2)
        layout.addLayout(product_bar)

        splitter = QSplitter(Qt.Orientation.Vertical)
        review_splitter = QSplitter(Qt.Orientation.Horizontal)
        grid_container = QWidget()
        grid_layout = QVBoxLayout(grid_container)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(8)
        filter_bar = QHBoxLayout()
        filter_bar.addWidget(controller.filter_edit, 1)
        filter_bar.addWidget(controller.warnings_only_checkbox)
        grid_layout.addLayout(filter_bar)
        grid_layout.addWidget(controller.table_view, 1)
        review_splitter.addWidget(grid_container)

        controller.detail_view.setMinimumWidth(340)
        detail_container = QWidget()
        self.detail_layout = QVBoxLayout(detail_container)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setSpacing(8)
        model_bar = QHBoxLayout()
        model_bar.addWidget(controller.provider_combo)
        model_bar.addWidget(controller.model_name_edit, 1)
        model_bar.addWidget(controller.ask_model_button)
        self.detail_layout.addLayout(model_bar)
        row_action_bar = QHBoxLayout()
        row_action_bar.addWidget(controller.use_support_button)
        row_action_bar.addWidget(controller.mark_row_reviewed_button)
        self.detail_layout.addLayout(row_action_bar)
        self.detail_layout.addWidget(controller.detail_view, 1)
        self.package_action_bar = QHBoxLayout()
        self.package_action_bar.addWidget(controller.go_to_output_folder_button)
        self.package_action_bar.addWidget(controller.build_package_button)
        self.detail_layout.addLayout(self.package_action_bar)
        review_splitter.addWidget(detail_container)
        review_splitter.setSizes([900, 360])
        splitter.addWidget(review_splitter)

        controller.issue_list.setMinimumHeight(120)
        controller.issue_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        issue_container = QWidget()
        issue_layout = QVBoxLayout(issue_container)
        issue_layout.setContentsMargins(0, 0, 0, 0)
        issue_layout.setSpacing(8)
        issue_layout.addWidget(controller.issue_list)
        issue_layout.addWidget(controller.mark_issue_reviewed_button)
        splitter.addWidget(issue_container)
        splitter.setSizes([560, 140])
        layout.addWidget(splitter, 1)
