#!/usr/bin/env python3
import os
import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from ui.mainwindow import MainWindow


def _read_version() -> str:
    for base in (Path(__file__).parent,
                 Path(getattr(__import__('sys'), '_MEIPASS', '.'))):
        p = base / 'VERSION'
        if p.exists():
            return p.read_text().strip()
    return '0.0.0'


def _frozen_icon_setup() -> None:
    """Restore system icon theme when running as PyInstaller bundle."""
    if not getattr(sys, 'frozen', False):
        return
    # Force GTK3 platform theme so QIcon.fromTheme() reads the user's theme
    os.environ.setdefault('QT_QPA_PLATFORMTHEME', 'gtk3')


def main() -> None:
    _frozen_icon_setup()
    app = QApplication(sys.argv)

    # After QApplication: ensure system icon paths and theme name are set
    if getattr(sys, 'frozen', False):
        paths = QIcon.themeSearchPaths()
        for p in ('/usr/share/icons', '/usr/local/share/icons',
                  str(Path.home() / '.local' / 'share' / 'icons')):
            if p not in paths:
                paths.append(p)
        QIcon.setThemeSearchPaths(paths)
        # If theme name is still blank/hicolor, try to read it from gsettings
        if QIcon.themeName() in ('', 'hicolor'):
            try:
                import subprocess
                name = subprocess.check_output(
                    ['gsettings', 'get', 'org.gnome.desktop.interface', 'icon-theme'],
                    text=True, timeout=2,
                ).strip().strip("'\"")
                if name:
                    QIcon.setThemeName(name)
            except Exception:
                pass
    app.setApplicationName("PDFTool")
    app.setOrganizationName("PDFTOOL")
    app.setApplicationVersion(_read_version())
    icon_path = Path(__file__).parent / "pdftool.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
