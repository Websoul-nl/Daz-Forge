from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class PoseConverterPage(QWidget):
    """Convert pose products into a new DIM package."""

    def __init__(self, controller: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._build_layout()

    def _build_layout(self) -> None:
        controller = self.controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        source_bar = QHBoxLayout()
        source_bar.addWidget(controller.pose_source_edit, 1)
        source_bar.addWidget(controller.pose_browse_source_button)
        layout.addLayout(source_bar)

        output_bar = QHBoxLayout()
        output_bar.addWidget(controller.pose_output_edit, 1)
        output_bar.addWidget(controller.pose_browse_output_button)
        output_bar.addWidget(controller.pose_open_output_button)
        layout.addLayout(output_bar)

        metadata_panel = QWidget()
        metadata_layout = QGridLayout(metadata_panel)
        metadata_layout.setContentsMargins(0, 0, 0, 0)
        metadata_layout.setHorizontalSpacing(10)
        metadata_layout.setVerticalSpacing(8)
        metadata_layout.addWidget(QLabel("Product"), 0, 0)
        metadata_layout.addWidget(controller.pose_product_name_edit, 0, 1, 1, 3)
        metadata_layout.addWidget(QLabel("Store"), 1, 0)
        metadata_layout.addWidget(controller.pose_store_combo, 1, 1, 1, 3)
        metadata_layout.addWidget(QLabel("Prefix"), 2, 0)
        metadata_layout.addWidget(controller.pose_store_prefix_edit, 2, 1)
        metadata_layout.addWidget(QLabel("Code"), 2, 2)
        metadata_layout.addWidget(controller.pose_store_code_edit, 2, 3)
        metadata_layout.addWidget(QLabel("Token"), 3, 0)
        metadata_layout.addWidget(controller.pose_token_edit, 3, 1)
        metadata_layout.addWidget(QLabel("GUID"), 3, 2)
        guid_bar = QHBoxLayout()
        guid_bar.setContentsMargins(0, 0, 0, 0)
        guid_bar.addWidget(controller.pose_guid_edit, 1)
        guid_bar.addWidget(controller.pose_generate_guid_button)
        metadata_layout.addLayout(guid_bar, 3, 3)
        metadata_layout.addWidget(QLabel("Artists"), 4, 0)
        metadata_layout.addWidget(controller.pose_artists_edit, 4, 1, 1, 3)
        metadata_layout.setColumnStretch(1, 1)
        metadata_layout.setColumnStretch(3, 1)
        layout.addWidget(metadata_panel)

        controller.pose_status_text.setReadOnly(True)
        layout.addWidget(controller.pose_status_text, 1)

        action_bar = QHBoxLayout()
        action_bar.addStretch(1)
        action_bar.addWidget(controller.pose_convert_button)
        layout.addLayout(action_bar)
