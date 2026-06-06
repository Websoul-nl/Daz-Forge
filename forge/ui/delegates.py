from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QCompleter, QStyledItemDelegate


CONTENT_TYPE_OPTIONS = (
    "Actor/Character",
    "Follower/Accessory",
    "Follower/Hair",
    "Follower/Wardrobe",
    "Preset/Materials",
    "Preset/Morph",
    "Preset/Pose",
    "Preset/Properties",
    "Preset/Shader",
    "Prop",
    "Scene",
    "Script/Documentation",
    "Script/Tool",
    "Script/Utility",
    "Set",
    "Support/UV Set",
)


class SearchableComboDelegate(QStyledItemDelegate):
    def __init__(self, options: tuple[str, ...], parent=None) -> None:
        super().__init__(parent)
        self.options = options

    def createEditor(self, parent, option, index):
        editor = QComboBox(parent)
        editor.setEditable(True)
        editor.addItems(self.options)
        editor.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        completer = QCompleter(self.options, editor)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        editor.setCompleter(completer)
        return editor

    def setEditorData(self, editor, index) -> None:
        value = index.data(Qt.ItemDataRole.EditRole) or ""
        editor.setEditText(str(value))

    def setModelData(self, editor, model, index) -> None:
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)
