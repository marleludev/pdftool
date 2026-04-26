"""Command pattern implementations for the undo/redo history.

Re-exports every concrete Command class so callers can do
``from core.commands import EditTextCmd`` if they prefer; the legacy
``from core.history import EditTextCmd`` form still works because
core.history re-imports from this package at the bottom.
"""
from core.commands.annot import AddAnnotCmd, DeleteAnnotCmd, MoveAnnotCmd
from core.commands.annot_text import (
    AnnotationTextCmd,
    DeleteAnnotTextCmd,
    TransformAnnotTextCmd,
)
from core.commands.group import GroupCmd
from core.commands.image import MoveDrawingCmd, MoveImageCmd, MoveImageWithSiblingsCmd
from core.commands.page import (
    DeletePageCmd,
    InsertPageCmd,
    MovePageCmd,
    ResizePageCmd,
    RotatePageCmd,
)
from core.commands.text import AddTextCmd, EditParagraphCmd, EditTextCmd, MoveTextCmd

__all__ = [
    "AddAnnotCmd",
    "DeleteAnnotCmd",
    "MoveAnnotCmd",
    "AnnotationTextCmd",
    "DeleteAnnotTextCmd",
    "TransformAnnotTextCmd",
    "GroupCmd",
    "MoveDrawingCmd",
    "MoveImageCmd",
    "MoveImageWithSiblingsCmd",
    "DeletePageCmd",
    "InsertPageCmd",
    "MovePageCmd",
    "ResizePageCmd",
    "RotatePageCmd",
    "AddTextCmd",
    "EditParagraphCmd",
    "EditTextCmd",
    "MoveTextCmd",
]
