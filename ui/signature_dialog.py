from __future__ import annotations

import shutil
from pathlib import Path

try:
    import qtawesome as qta
    QTA_AVAILABLE = True
except ImportError:
    QTA_AVAILABLE = False

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

_SIG_DIR = Path.home() / ".config" / "PDFTool" / "signatures"
_NUM_SLOTS = 4
_PREVIEW_W = 160
_PREVIEW_H = 96


def _icon(name: str) -> QIcon:
    """Get icon from qtawesome."""
    if QTA_AVAILABLE:
        try:
            return qta.icon(f"mdi.{name}", color="#555555")
        except Exception:
            pass
    return QIcon()


def sig_path(slot: int) -> Path:
    return _SIG_DIR / f"signature{slot}.png"


class _SlotWidget(QGroupBox):
    place_requested = pyqtSignal(int)

    def __init__(self, slot: int, parent=None) -> None:
        super().__init__(f"Signature {slot}", parent)
        self._slot = slot

        self._preview = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self._preview.setFixedSize(_PREVIEW_W, _PREVIEW_H)
        self._preview.setStyleSheet(
            "border: 1px solid #bbb; background: #f5f5f5; border-radius: 3px;"
        )

        self._btn_load = QPushButton(_icon("folder-open"), " Load…")
        self._btn_clear = QPushButton(_icon("close"), " Clear")
        self._btn_place = QPushButton(_icon("draw"), " Place")
        self._btn_place.setStyleSheet("font-weight: bold;")

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._btn_load)
        btn_row.addWidget(self._btn_clear)

        vbox = QVBoxLayout(self)
        vbox.addWidget(self._preview)
        vbox.addLayout(btn_row)
        vbox.addWidget(self._btn_place)

        self._btn_load.clicked.connect(self._load)
        self._btn_clear.clicked.connect(self._clear)
        self._btn_place.clicked.connect(lambda: self.place_requested.emit(self._slot))

        self._refresh()

    def _refresh(self) -> None:
        p = sig_path(self._slot)
        has = p.exists()
        self._btn_clear.setEnabled(has)
        self._btn_place.setEnabled(has)
        if has:
            pm = QPixmap(str(p))
            self._preview.setPixmap(
                pm.scaled(
                    _PREVIEW_W,
                    _PREVIEW_H,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self._preview.setText("")
        else:
            self._preview.setPixmap(QPixmap())
            self._preview.setText("(empty)")

    def _load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Load Signature {self._slot}",
            str(Path.home()),
            "PNG images (*.png)",
        )
        if not path:
            return
        _SIG_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, sig_path(self._slot))
        self._refresh()

    def _clear(self) -> None:
        p = sig_path(self._slot)
        if p.exists():
            p.unlink()
        self._refresh()


class SignatureDialog(QDialog):
    place_requested = pyqtSignal(int)  # slot number 1–4

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Signatures")
        self.setWindowIcon(_icon("draw"))
        self.setModal(True)

        grid = QGridLayout()
        grid.setSpacing(12)
        for i in range(_NUM_SLOTS):
            slot = _SlotWidget(i + 1, self)
            slot.place_requested.connect(self._on_place)
            grid.addWidget(slot, i // 2, i % 2)

        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.reject)

        vbox = QVBoxLayout(self)
        vbox.addLayout(grid)
        vbox.addWidget(close_box)

    def _on_place(self, slot: int) -> None:
        self.place_requested.emit(slot)
        self.accept()
