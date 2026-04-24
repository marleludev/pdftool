from __future__ import annotations

import fitz
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)


class EncryptDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Encrypt PDF")
        self.setMinimumWidth(420)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        owner_group = QGroupBox("Owner Password (controls editing / permissions)")
        owner_form = QFormLayout(owner_group)
        self._owner_pw = QLineEdit()
        self._owner_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self._owner_pw.setPlaceholderText("Required")
        self._owner_pw2 = QLineEdit()
        self._owner_pw2.setEchoMode(QLineEdit.EchoMode.Password)
        self._owner_pw2.setPlaceholderText("Repeat")
        owner_form.addRow("Password:", self._owner_pw)
        owner_form.addRow("Confirm:", self._owner_pw2)
        layout.addWidget(owner_group)

        user_group = QGroupBox("User Password (required to open — leave blank for none)")
        user_form = QFormLayout(user_group)
        self._user_pw = QLineEdit()
        self._user_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self._user_pw.setPlaceholderText("Optional")
        self._user_pw2 = QLineEdit()
        self._user_pw2.setEchoMode(QLineEdit.EchoMode.Password)
        self._user_pw2.setPlaceholderText("Repeat")
        user_form.addRow("Password:", self._user_pw)
        user_form.addRow("Confirm:", self._user_pw2)
        layout.addWidget(user_group)

        perm_group = QGroupBox("Permissions (what users without owner password may do)")
        perm_layout = QVBoxLayout(perm_group)
        self._perm_print = QCheckBox("Allow printing")
        self._perm_print.setChecked(True)
        self._perm_copy = QCheckBox("Allow copying text / images")
        self._perm_modify = QCheckBox("Allow modifying document")
        self._perm_annotate = QCheckBox("Allow annotations and form filling")
        for cb in (self._perm_print, self._perm_copy, self._perm_modify, self._perm_annotate):
            perm_layout.addWidget(cb)
        layout.addWidget(perm_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate_and_accept(self) -> None:
        owner = self._owner_pw.text()
        if not owner:
            QMessageBox.warning(self, "Missing password", "Owner password is required.")
            self._owner_pw.setFocus()
            return
        if owner != self._owner_pw2.text():
            QMessageBox.warning(self, "Mismatch", "Owner passwords do not match.")
            self._owner_pw2.setFocus()
            return
        user = self._user_pw.text()
        if user and user != self._user_pw2.text():
            QMessageBox.warning(self, "Mismatch", "User passwords do not match.")
            self._user_pw2.setFocus()
            return
        self.accept()

    @property
    def owner_password(self) -> str:
        return self._owner_pw.text()

    @property
    def user_password(self) -> str:
        return self._user_pw.text()

    @property
    def permissions(self) -> int:
        perms = 0
        if self._perm_print.isChecked():
            perms |= fitz.PDF_PERM_PRINT | fitz.PDF_PERM_PRINT_HQ
        if self._perm_copy.isChecked():
            perms |= fitz.PDF_PERM_COPY
        if self._perm_modify.isChecked():
            perms |= fitz.PDF_PERM_MODIFY | fitz.PDF_PERM_ASSEMBLE
        if self._perm_annotate.isChecked():
            perms |= fitz.PDF_PERM_ANNOTATE | fitz.PDF_PERM_FORM
        return perms
