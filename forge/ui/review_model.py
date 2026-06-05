from __future__ import annotations

from copy import deepcopy
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


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
        if contract is not None:
            self.set_contract(contract)

    def set_contract(self, contract: dict[str, Any]) -> None:
        self.beginResetModel()
        self._contract = deepcopy(contract)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self.COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        row = self._rows[index.row()]
        column = self.COLUMNS[index.column()]

        if role in {Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole}:
            return self._display_value(row, column)
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip_value(row, column)
        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        if index.row() >= len(self._rows):
            return False
        column = self.COLUMNS[index.column()]
        if column not in self.EDITABLE_COLUMNS:
            return False

        row = self._rows[index.row()]
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

    @property
    def _rows(self) -> list[dict[str, Any]]:
        return self._contract.setdefault("rows", [])

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


def _join_values(values: list[str] | tuple[str, ...] | str) -> str:
    if isinstance(values, str):
        return values
    return "; ".join(str(value) for value in values if str(value))


def _split_values(value: str) -> list[str]:
    if not value:
        return []
    normalized = value.replace("\n", ";").replace(",", ";")
    return [part.strip() for part in normalized.split(";") if part.strip()]
