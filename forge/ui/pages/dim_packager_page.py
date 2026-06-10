from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from forge.ui.widgets.product_image import ProductImageDropZone


class DimPackagerPage(QWidget):
    """Review and package one DAZ product as a DIM zip."""

    def __init__(self, controller: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.detail_layout: QVBoxLayout
        self.footer_layout: QVBoxLayout
        self.package_action_bar: QHBoxLayout
        self.product_tab: QWidget
        self.product_image_tab: QWidget
        self.selected_file_tab: QWidget
        self.source_toolbar: QWidget
        self.inspector_tabs: QTabWidget
        self._build_layout()

    def _build_layout(self) -> None:
        controller = self.controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.source_toolbar = QWidget()
        source_bar = QHBoxLayout(self.source_toolbar)
        source_bar.setContentsMargins(0, 0, 0, 0)
        source_bar.setSpacing(8)
        source_bar.addWidget(controller.source_edit, 1)
        source_bar.addWidget(controller.browse_button)
        source_bar.addWidget(controller.analyze_button)
        layout.addWidget(self.source_toolbar)

        layout.addWidget(controller.summary_label)

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

        self.inspector_tabs = QTabWidget()
        self.inspector_tabs.setMinimumWidth(380)
        self.product_tab = self._build_product_tab()
        self.product_image_tab = self._build_product_image_tab()
        self.selected_file_tab = self._build_selected_file_tab()
        self.inspector_tabs.addTab(self.product_tab, "Product")
        self.inspector_tabs.addTab(self.product_image_tab, "Product Image")
        self.inspector_tabs.addTab(self.selected_file_tab, "Selected File")
        review_splitter.addWidget(self.inspector_tabs)
        review_splitter.setSizes([920, 380])
        layout.addWidget(review_splitter, 1)

        controller.issue_list.setMinimumHeight(108)
        controller.issue_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        footer_container = QWidget()
        self.footer_layout = QVBoxLayout(footer_container)
        self.footer_layout.setContentsMargins(0, 0, 0, 0)
        self.footer_layout.setSpacing(8)
        self.footer_layout.addWidget(controller.issue_list)
        self.package_action_bar = QHBoxLayout()
        self.package_action_bar.addWidget(controller.mark_issue_reviewed_button)
        self.package_action_bar.addStretch(1)
        self.package_action_bar.addWidget(controller.go_to_output_folder_button)
        self.package_action_bar.addWidget(controller.build_package_button)
        self.footer_layout.addLayout(self.package_action_bar)
        layout.addWidget(footer_container)

    def _build_product_tab(self) -> QWidget:
        controller = self.controller
        tab = QWidget()
        layout = QGridLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(8)
        layout.addWidget(QLabel("Product"), 0, 0)
        layout.addWidget(controller.product_name_edit, 0, 1, 1, 3)
        layout.addWidget(QLabel("Store"), 1, 0)
        layout.addWidget(controller.store_combo, 1, 1, 1, 3)
        layout.addWidget(QLabel("Prefix"), 2, 0)
        layout.addWidget(controller.store_prefix_edit, 2, 1)
        layout.addWidget(QLabel("Code"), 2, 2)
        layout.addWidget(controller.store_code_edit, 2, 3)
        layout.addWidget(QLabel("Token"), 3, 0)
        layout.addWidget(controller.token_edit, 3, 1, 1, 3)
        layout.addWidget(QLabel("GUID"), 4, 0)
        layout.addWidget(controller.guid_edit, 4, 1, 1, 2)
        layout.addWidget(controller.generate_guid_button, 4, 3)
        layout.addWidget(QLabel("Artists"), 5, 0)
        layout.addWidget(controller.artists_edit, 5, 1, 1, 3)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)
        layout.setRowStretch(6, 1)
        return tab

    def _build_product_image_tab(self) -> QWidget:
        controller = self.controller
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(QLabel("Product image"))
        controller.product_image_drop_zone = ProductImageDropZone(controller.set_product_image_path)
        layout.addWidget(controller.product_image_drop_zone, 1)
        controller.product_image_path_edit.setReadOnly(True)
        layout.addWidget(controller.product_image_path_edit)
        button_bar = QHBoxLayout()
        button_bar.addStretch(1)
        button_bar.addWidget(controller.choose_product_image_button)
        layout.addLayout(button_bar)
        return tab

    def _build_selected_file_tab(self) -> QWidget:
        controller = self.controller
        tab = QWidget()
        controller.detail_view.setMinimumWidth(340)
        self.detail_layout = QVBoxLayout(tab)
        self.detail_layout.setContentsMargins(12, 12, 12, 12)
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
        return tab
