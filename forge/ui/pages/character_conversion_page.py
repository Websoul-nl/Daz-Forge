from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QPlainTextEdit, QVBoxLayout, QWidget,
)

from forge.material_converter.character import BUNDLED_TRANSFERS, PBR, UBER, UV_NAMES, convert_character, inspect_skin
from forge.material_converter.pbr_presets import read_dson
from forge.material_converter.product import load_character_product


class CharacterWorker(QObject):
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, args, settings):
        super().__init__()
        self.args, self.settings = args, settings

    @Slot()
    def run(self):
        try:
            result = convert_character(*self.args, **self.settings, progress=self.progress.emit)
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.finished.emit(result)


class CharacterConversionPage(QWidget):
    def __init__(self, *, output="", parent=None):
        super().__init__(parent)
        self.thread = None
        self.worker = None
        self.source = None
        self.product = None
        self.skin_path = None
        self.report_path = None
        self.preset = QLineEdit()
        self.preset.setAcceptDrops(False)
        self.name = QLineEdit()
        self.library = QLineEdit()
        self.transfer = QLineEdit()
        self.transfer.setPlaceholderText("Use bundled transfers")
        self.variants = QLineEdit()
        self.output = QLineEdit(output)
        self.uv = QComboBox()
        self.uv.addItems(("Detect from preset", *UV_NAMES))
        self.route = QLabel("No skin inspected")
        self.include_pbr = QCheckBox("Also export PBRSkin")
        self.include_pbr.hide()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.review = QPlainTextEdit()
        self.review.setReadOnly(True)
        self.review.setAcceptDrops(False)
        self.skin_choices = QComboBox()
        self.skin_choices.hide()
        self.inspect_button = QPushButton("Inspect Source")
        self.convert_button = QPushButton("Export Materials")
        self.convert_button.setEnabled(False)
        self.open_button = QPushButton("Open Export")
        self.open_button.setEnabled(False)
        self._rows = []

        form = QFormLayout()
        form.addRow("Source DUF or product DSX", self._path_row(self.preset, file=True))
        form.addRow(self.skin_choices)
        form.addRow("Character name", self.name)
        form.addRow("Source UV", self.uv)
        form.addRow("Genesis 9 base library", self._path_row(self.library))
        self.transfer_row = self._path_row(self.transfer)
        form.addRow("UV transfer override", self.transfer_row)
        form.setRowVisible(self.transfer_row, not any(BUNDLED_TRANSFERS.glob("*.json")))
        self.variant_row = self._path_row(self.variants)
        form.addRow("Variant folder (optional)", self.variant_row)
        self.form = form
        form.addRow("Export folder", self._path_row(self.output))
        form.addRow("Export shader", self.route)
        form.addRow("", self.include_pbr)
        actions = QHBoxLayout()
        actions.addStretch(1)
        for button in (self.inspect_button, self.convert_button, self.open_button):
            actions.addWidget(button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.addLayout(form)
        layout.addLayout(actions)
        layout.addWidget(self.status)
        layout.addWidget(QLabel("Review"))
        layout.addWidget(self.review, 1)

        self.preset.textChanged.connect(self._reset)
        self.uv.currentIndexChanged.connect(self._inspect_skin)
        self.skin_choices.currentIndexChanged.connect(self._inspect_skin)
        self.inspect_button.clicked.connect(self.inspect)
        self.preset.returnPressed.connect(self.inspect)
        self.convert_button.clicked.connect(self._convert)
        self.open_button.clicked.connect(self._open)

    def _path_row(self, edit, *, file=False):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        browse = QPushButton("Browse")
        browse.clicked.connect(lambda: self._browse(edit, file))
        layout.addWidget(edit, 1)
        layout.addWidget(browse)
        self._rows.append(row)
        return row

    def _browse(self, edit, file):
        if file:
            path, _ = QFileDialog.getOpenFileName(self, "Select Character Source", edit.text(), "DAZ sources (*.duf *.dsx)")
        else:
            path = QFileDialog.getExistingDirectory(self, "Select Folder", edit.text())
        if path:
            if file:
                self.set_source(Path(path))
            else:
                edit.setText(path)

    def set_source(self, path: Path):
        if not self.is_running():
            self.preset.setText(str(path))
            self.inspect()

    def _reset(self):
        self.product = None
        self.skin_path = None
        self.skin_choices.blockSignals(True)
        self.skin_choices.clear()
        self.skin_choices.blockSignals(False)
        self.skin_choices.hide()
        self.form.setRowVisible(self.variant_row, True)
        self._reset_skin()

    def _reset_skin(self):
        self.source = None
        self.route.setText("No skin inspected")
        self.status.clear()
        self.include_pbr.setChecked(False)
        self.include_pbr.hide()
        self.convert_button.setEnabled(False)

    def _confirmed_uv(self):
        return self.uv.currentText() if self.uv.currentIndex() else None

    @Slot()
    def inspect(self):
        self._reset()
        if not self.preset.text().strip():
            return
        path = Path(self.preset.text().strip())
        if path.suffix.casefold() == ".dsx":
            try:
                self.product = load_character_product(path)
            except (OSError, ValueError, KeyError) as exc:
                self.status.setText(str(exc))
                return
            self.form.setRowVisible(self.variant_row, False)
            if not self.name.text().strip():
                self.name.setText(self.product.name)
            if not self.product.skins:
                self.status.setText("The product has no supported, installed full-skin presets.")
                return
            self.skin_choices.blockSignals(True)
            for candidate in self.product.skins:
                self.skin_choices.addItem(candidate.label, candidate.path)
            if len(self.product.skins) > 1:
                self.skin_choices.setPlaceholderText("Choose a full-skin preset")
                self.skin_choices.setCurrentIndex(-1)
            self.skin_choices.blockSignals(False)
            self.skin_choices.show()
        self._inspect_skin()

    @Slot()
    def _inspect_skin(self):
        self._reset_skin()
        path = self.skin_choices.currentData() if self.product else (
            Path(self.preset.text().strip()) if self.preset.text().strip() else None
        )
        if path is None:
            if self.product and self.product.skins:
                self.status.setText("Choose which full skin to convert.")
            return
        if path.suffix.casefold() != ".duf":
            return
        self.skin_path = path
        try:
            self.source = inspect_skin(read_dson(path), self._confirmed_uv())
        except (OSError, ValueError, KeyError) as exc:
            self.status.setText(str(exc))
            return
        self.route.setText(self.source.routes[0])
        self.include_pbr.setVisible(self.source.shader == UBER)
        self.status.setText(f"{self.source.generation} | {self.source.uv} | {self.source.shader}")
        self.convert_button.setEnabled(True)

    def is_running(self):
        return self.thread is not None

    def _set_running(self, running):
        for widget in (*self._rows, self.name, self.uv, self.skin_choices, self.include_pbr, self.inspect_button):
            widget.setEnabled(not running)
        self.convert_button.setEnabled(not running and self.source is not None)
        self.open_button.setEnabled(not running and self.report_path is not None)

    @Slot()
    def _convert(self):
        if self.thread is not None or not self.source:
            return
        required = (self.library, self.output, self.name)
        if any(not field.text().strip() for field in required):
            self.status.setText("Select the base library and export folder; enter the character name.")
            return
        self.report_path = None
        self.review.clear()
        self._set_running(True)
        override = Path(self.transfer.text().strip()) if self.transfer.text().strip() else None
        args = self.skin_path, Path(self.library.text().strip()), override, Path(self.output.text().strip())
        options = {
            "character_name": self.name.text().strip(), "confirmed_uv": self._confirmed_uv(),
            "include_pbr": self.source.shader != PBR and self.include_pbr.isChecked(),
            "variants_folder": Path(self.variants.text().strip()) if not self.product and self.variants.text().strip() else None,
            "product_dsx": self.product.manifest if self.product else None,
        }
        self.thread = QThread(self)
        self.worker = CharacterWorker(args, options)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.status.setText)
        self.worker.finished.connect(self._finish)
        self.worker.failed.connect(self._fail)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._thread_done)
        self.thread.start()

    @Slot(object)
    def _finish(self, result):
        self.report_path = result.report
        try:
            data = json.loads(result.report.read_text(encoding="utf-8"))
            grouped = {}
            for entry in data["review"]:
                key = entry["route"], entry.get("channel"), entry["reason"]
                grouped.setdefault(key, []).append(entry["target"])
            entries = [
                f"{route} / {', '.join(targets)}{' / ' + channel if channel else ''}: {reason}"
                for (route, channel, reason), targets in grouped.items()
            ]
            self.review.setPlainText("\n".join(entries) if entries else "No manual review items.")
            self.status.setText(f"Exported {len(result.presets)} preset(s). {result.review_count} review item(s).")
        except (OSError, ValueError, KeyError) as exc:
            self.status.setText(f"Export succeeded, but the review could not be displayed: {exc}")
        finally:
            self.thread.quit()

    @Slot(str)
    def _fail(self, message):
        self.status.setText("Export failed: " + message)
        self.thread.quit()

    @Slot()
    def _thread_done(self):
        self.thread = self.worker = None
        self._set_running(False)

    @Slot()
    def _open(self):
        if self.report_path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.report_path.parent)))
