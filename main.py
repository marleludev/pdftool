#!/usr/bin/env python3
import sys

from PyQt6.QtWidgets import QApplication

from ui.mainwindow import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("PDFTool")
    app.setOrganizationName("PDFTOOL")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
