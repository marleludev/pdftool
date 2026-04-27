"""Settings dialog for text annotation defaults: font, size, and preview."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QFrame,
)


def _get_system_fonts() -> list[str]:
    """Query fc-list for available system fonts, fallback to common fonts."""
    try:
        result = subprocess.run(
            ["fc-list", ":", "family"],
            capture_output=True,
            timeout=5,
            text=True,
        )
        families = set()
        for line in result.stdout.split('\n'):
            if ',' in line:
                line = line.split(',')[0]
            name = line.strip()
            if name:
                families.add(name)
        if families:
            return sorted(families)
    except Exception:
        pass

    return [
        "DejaVu Sans", "DejaVu Serif", "Liberation Sans", "Liberation Serif",
        "Ubuntu", "Noto Sans", "Helvetica", "Times", "Courier", "Arial",
        "Verdana", "Georgia", "Consolas", "Monospace", "Sans Serif", "Serif"
    ]


class SettingsDialog(QDialog):
    """Text annotation defaults: font, size, file size warning."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(500)

        self._settings = QSettings("PDFTool", "PDFTool")

        # Load current values
        self._current_font = self._settings.value(
            "annotationFont", "DejaVu Sans", str
        )
        self._current_size = self._settings.value(
            "annotationFontSize", 12.0, float
        )

        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        layout = QVBoxLayout()

        # Group: Text Annotation Defaults
        group = QGroupBox("Text Annotation Defaults")
        group_layout = QVBoxLayout()

        # Font selection
        font_layout = QHBoxLayout()
        font_layout.addWidget(QLabel("Font:"))
        self._font_combo = QComboBox()
        self._font_combo.addItems(_get_system_fonts())
        self._font_combo.setEditable(True)
        font_layout.addWidget(self._font_combo)
        self._font_combo.currentTextChanged.connect(self._on_font_changed)
        group_layout.addLayout(font_layout)

        # Font size
        size_layout = QHBoxLayout()
        size_layout.addWidget(QLabel("Size (pt):"))
        self._size_spin = QDoubleSpinBox()
        self._size_spin.setRange(6.0, 72.0)
        self._size_spin.setSingleStep(1.0)
        size_layout.addWidget(self._size_spin)
        self._size_spin.valueChanged.connect(self._on_size_changed)
        group_layout.addLayout(size_layout)

        group.setLayout(group_layout)
        layout.addWidget(group)

        # Group: Font Info
        info_group = QGroupBox("Font Information")
        info_layout = QVBoxLayout()

        self._info_text = QTextEdit()
        self._info_text.setReadOnly(True)
        self._info_text.setMaximumHeight(200)
        self._info_text.setFont(QFont("Monospace", 9))
        info_layout.addWidget(self._info_text)

        # File size warning
        self._size_warning = QLabel()
        self._size_warning.setWordWrap(True)
        self._size_warning.setStyleSheet("color: #cc6600;")
        info_layout.addWidget(self._size_warning)

        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        button_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def _load_values(self) -> None:
        """Load saved preferences into UI."""
        idx = self._font_combo.findText(self._current_font, Qt.MatchFlag.MatchExactly)
        if idx >= 0:
            self._font_combo.setCurrentIndex(idx)
        else:
            self._font_combo.setCurrentText(self._current_font)
        self._size_spin.setValue(self._current_size)
        self._update_info()

    def _on_font_changed(self) -> None:
        """Refresh info when font changes."""
        self._update_info()

    def _on_size_changed(self) -> None:
        """Refresh info when size changes."""
        self._update_info()

    def _update_info(self) -> None:
        """Show font path, embedding status, file size estimate."""
        font_name = self._font_combo.currentText()
        font_path = self._find_font_path(font_name)

        if font_path:
            file_size_kb = font_path.stat().st_size / 1024
            info = f"Font: {font_name}\n"
            info += f"Path: {font_path}\n"
            info += f"File size: {file_size_kb:.1f} KB\n"
            info += f"\nStatus: System font (will be embedded)"
            self._size_warning.setText(
                f"⚠ This font will be embedded in the PDF at first use. "
                f"Adds ~{file_size_kb:.0f} KB to document size."
            )
        else:
            info = f"Font: {font_name}\n"
            info += "Path: Not found\n"
            info += "File size: —\n"
            info += f"\nStatus: Will fall back to Helvetica"
            self._size_warning.setText(
                "⚠ Font not found on system. Annotation text will use Helvetica."
            )

        self._info_text.setText(info)

    def _find_font_path(self, font_name: str) -> Path | None:
        """Query system for font file path via fc-match."""
        try:
            result = subprocess.run(
                ["fc-match", font_name, "--format=%{file}"],
                capture_output=True,
                timeout=2,
                text=True,
            )
            path_str = result.stdout.strip()
            if path_str and Path(path_str).exists():
                return Path(path_str)
        except Exception:
            pass
        return None

    def get_font(self) -> str:
        """Get selected font name."""
        return self._font_combo.currentText()

    def get_size(self) -> float:
        """Get selected font size in points."""
        return self._size_spin.value()

    def accept(self) -> None:
        """Save settings and close."""
        self._settings.setValue("annotationFont", self.get_font())
        self._settings.setValue("annotationFontSize", self.get_size())
        super().accept()
