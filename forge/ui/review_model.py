from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor


class ReviewTableModel(QAbstractTableModel):
    COLUMNS = (
        "File",
        "Content Type",
        "Category",
        "Compatibility Base",
        "Compatibilities",
        "Warnings",
        "Model",
        "Support",
    )
    EDITABLE_COLUMNS = {"Content Type", "Category", "Compatibility Base", "Compatibilities"}

    def __init__(self, contract: dict[str, Any] | None = None) -> None:
        super().__init__()
        self._contract: dict[str, Any] = {"rows": []}
        self._filter_text = ""
        self._warnings_only = False
        self._visible_row_indexes: list[int] = []
        if contract is not None:
            self.set_contract(contract)

    def set_contract(self, contract: dict[str, Any]) -> None:
        self.beginResetModel()
        self._contract = deepcopy(contract)
        self._refresh_visible_rows()
        self.endResetModel()

    def set_filter_text(self, text: str) -> None:
        self.beginResetModel()
        self._filter_text = text.strip().lower()
        self._refresh_visible_rows()
        self.endResetModel()

    def set_warnings_only(self, enabled: bool) -> None:
        self.beginResetModel()
        self._warnings_only = enabled
        self._refresh_visible_rows()
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._visible_row_indexes)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self.COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._visible_row_indexes):
            return None
        row = self._visible_row(index.row())
        column = self.COLUMNS[index.column()]

        if role in {Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole}:
            return self._display_value(row, column)
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip_value(row, column)
        if role == Qt.ItemDataRole.BackgroundRole and row.get("warnings"):
            return QColor("#3b3023")
        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        if index.row() >= len(self._visible_row_indexes):
            return False
        column = self.COLUMNS[index.column()]
        if column not in self.EDITABLE_COLUMNS:
            return False

        row = self._visible_row(index.row())
        final = row.setdefault("final", {})
        text = str(value).strip()
        if column == "Content Type":
            final["content_type"] = text
        elif column == "Category":
            final["categories"] = _split_values(text)
        elif column == "Compatibility Base":
            final["compatibility_base"] = text
        elif column == "Compatibilities":
            final["compatibilities"] = _split_values(text)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole])
        return True

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        flags = super().flags(index)
        if index.isValid() and self.COLUMNS[index.column()] in self.EDITABLE_COLUMNS:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section]
        return super().headerData(section, orientation, role)

    def column_index(self, name: str) -> int:
        return self.COLUMNS.index(name)

    def approved_rows(self) -> list[dict[str, Any]]:
        return deepcopy(self._rows)

    def visible_row_count(self) -> int:
        return len(self._visible_row_indexes)

    def total_row_count(self) -> int:
        return len(self._rows)

    def row_details(self, visible_row: int) -> str:
        if visible_row < 0 or visible_row >= len(self._visible_row_indexes):
            return "No row selected"
        row = self._visible_row(visible_row)
        sections = [
            row.get("path", ""),
            "",
            _metadata_block("Final", row.get("final")),
            _metadata_block("Deterministic", row.get("deterministic")),
            _metadata_block("Model", row.get("model")),
            _metadata_block("Support", row.get("support")),
        ]
        warnings = row.get("warnings", [])
        if warnings:
            sections.extend(["Warnings", _join_values(warnings)])
        return "\n".join(section for section in sections if section is not None)

    def apply_support_to_row(self, visible_row: int) -> bool:
        return self._apply_metadata_to_row(visible_row, "support")

    def apply_model_to_row(self, visible_row: int) -> bool:
        return self._apply_metadata_to_row(visible_row, "model")

    def mark_row_reviewed(self, visible_row: int) -> bool:
        if visible_row < 0 or visible_row >= len(self._visible_row_indexes):
            return False
        row = self._visible_row(visible_row)
        row["warnings"] = []
        self._refresh_visible_rows()
        self.layoutChanged.emit()
        return True

    def _apply_metadata_to_row(self, visible_row: int, source_key: str) -> bool:
        if visible_row < 0 or visible_row >= len(self._visible_row_indexes):
            return False
        row = self._visible_row(visible_row)
        source = row.get(source_key)
        if not source:
            return False
        final = row.setdefault("final", {})
        for key in ("content_type", "categories", "compatibility_base", "compatibilities"):
            final[key] = deepcopy(source.get(key, [] if key in {"categories", "compatibilities"} else ""))
        row["warnings"] = []
        self._refresh_visible_rows()
        self.layoutChanged.emit()
        return True

    def row_warning_messages(self) -> list[str]:
        messages: list[str] = []
        for row in self._rows:
            for warning in row.get("warnings", []):
                messages.append(f"{row.get('path', '')}: {warning}")
        return messages

    @property
    def _rows(self) -> list[dict[str, Any]]:
        return self._contract.setdefault("rows", [])

    def _visible_row(self, visible_row: int) -> dict[str, Any]:
        return self._rows[self._visible_row_indexes[visible_row]]

    def _refresh_visible_rows(self) -> None:
        self._visible_row_indexes = [
            index for index, row in enumerate(self._rows)
            if self._row_matches(row)
        ]

    def _row_matches(self, row: dict[str, Any]) -> bool:
        if self._warnings_only and not row.get("warnings"):
            return False
        if not self._filter_text:
            return True
        return self._filter_text in json.dumps(row, sort_keys=True).lower()

    def _display_value(self, row: dict[str, Any], column: str) -> str:
        final = row.get("final", {})
        if column == "File":
            return row.get("path", "")
        if column == "Content Type":
            return final.get("content_type", "")
        if column == "Category":
            return _join_values(final.get("categories", []))
        if column == "Compatibility Base":
            return final.get("compatibility_base", "")
        if column == "Compatibilities":
            return _join_values(final.get("compatibilities", []))
        if column == "Warnings":
            return _join_values(row.get("warnings", []))
        if column == "Model":
            return _metadata_summary(row.get("model"))
        if column == "Support":
            return _metadata_summary(row.get("support"))
        return ""

    def _tooltip_value(self, row: dict[str, Any], column: str) -> str:
        if column == "Model":
            model = row.get("model")
            if model:
                return model.get("reason", "")
        return self._display_value(row, column)


def _metadata_summary(value: dict[str, Any] | None) -> str:
    if not value:
        return ""
    content_type = value.get("content_type", "")
    categories = _join_values(value.get("categories", []))
    if content_type and categories:
        return f"{content_type} | {categories}"
    return content_type or categories


def _metadata_block(label: str, value: dict[str, Any] | None) -> str:
    if not value:
        return f"{label}\n  -"
    lines = [label]
    content_type = value.get("content_type", "")
    categories = _join_values(value.get("categories", []))
    compatibility_base = value.get("compatibility_base", "")
    compatibilities = _join_values(value.get("compatibilities", []))
    confidence = value.get("confidence", "")
    reason = value.get("reason", "")
    if content_type:
        lines.append(f"  Type: {content_type}")
    if categories:
        lines.append(f"  Category: {categories}")
    if compatibility_base:
        lines.append(f"  Base: {compatibility_base}")
    if compatibilities:
        lines.append(f"  Compatible: {compatibilities}")
    if confidence != "":
        lines.append(f"  Confidence: {confidence}")
    if reason:
        lines.append(f"  Reason: {reason}")
    return "\n".join(lines)


def _join_values(values: list[str] | tuple[str, ...] | str) -> str:
    if isinstance(values, str):
        return values
    return "; ".join(str(value) for value in values if str(value))


def _split_values(value: str) -> list[str]:
    if not value:
        return []
    normalized = value.replace("\n", ";").replace(",", ";")
    return [part.strip() for part in normalized.split(";") if part.strip()]
