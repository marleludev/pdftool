# Version Notes - PDFTool v0.5.0

**Release Date**: 2026-04-25

## Summary

Page geometry tools and image compression. Pages can now be resized to standard paper formats or custom dimensions (with scale/keep/crop content modes) and rotated 90° in either direction. Embedded images can be downsampled to a target DPI to reduce file size. Highlight annotations now support color selection from a toolbar dropdown. The Properties dialog shows page count and size in mm/inches with standard paper name detection.

---

## New Features

### Highlight Color Picker

- Toolbar highlight button now has a drop-down menu with color swatches: yellow, green, cyan, pink, orange
- Selected color persists for the session; default remains yellow
- Color stored in annotation data and applied via `set_colors(stroke=...)` on the fitz annotation
- `apply_highlight()` in `core/document.py` accepts optional `color` parameter

### Reduce Image DPI (`Document → Reduce Image DPI`)

- Scans all embedded images in the document and reports count and current file size
- Target DPI spinner (72–600, step 25); live estimate of resulting file size and savings
- Opaque images re-encoded as JPEG quality 85; transparent images as PNG
- Only images whose native DPI exceeds the target are downsampled (LANCZOS resampling)
- Last-used DPI saved to settings (`compressImagesDpi` key)

### Resize Page (`Document → Resize Page` / thumbnail context menu)

- Paper format presets: A2, A3, A4, A5, A6, Letter, Legal, Tabloid, Executive, Custom
- Portrait / landscape toggle; custom dimensions in mm with live pt preview
- Apply to current page only or all pages
- Three content handling modes:
  - **Scale** — content scaled to fill new dimensions (flattened to XObject)
  - **Keep** — page box resized, content stays at original coordinates
  - **Crop** — same as keep; new mediabox clips anything outside
- Also accessible via right-click on thumbnail → "Resize page…"
- Full undo support via `ResizePageCmd` (snapshots page bytes before resize)

### Page Rotation

- Right-click thumbnail → "Rotate 90° clockwise" or "Rotate 90° counter-clockwise"
- Full undo support via `RotatePageCmd`
- Rotation stored as PDF page rotation (non-destructive)

### Properties Dialog: Page Size Info

- Shows page count and page size for all open documents
- Size displayed as mm and inches with standard paper name detection (A4, Letter, Legal, etc.)
- Landscape orientation detected and labeled (e.g. "A4 (landscape)")
- Mixed page sizes shown as "Various — Page 1: …"

---

## Files Modified

| File | Description |
|------|-------------|
| `ui/compress_dialog.py` | New — image DPI scan, estimate, and downsample dialog |
| `ui/resize_page_dialog.py` | New — page resize dialog with format presets and content mode |
| `core/document.py` | `resize_page()` method; `apply_highlight()` color parameter |
| `core/history.py` | `ResizePageCmd`, `RotatePageCmd` added |
| `tools/annotate.py` | `HighlightTool` accepts color; toolbar color picker dropdown |
| `ui/mainwindow.py` | Compress/resize actions in Document menu; highlight color picker; page rotate/resize signal wiring |
| `ui/properties_dialog.py` | Page count and size display with paper name detection |
| `ui/thumbnail_panel.py` | Context menu: resize page, rotate CW/CCW; new signals |
| `VERSION` | Bumped to 0.5.0 |

---

# Version Notes - PDFTool v0.4.0

**Release Date**: 2026-04-24

## Summary

Multi-tab PDF editing and lighter icon style. Multiple PDFs can now be open simultaneously in separate tabs. Icons switched to outline (regular) variants where available and lightened to reduce visual weight.

---

## New Features

### Multi-Tab PDF Editing

- **File → Open** (Ctrl+O): if current tab already has a document, the new file opens in a new tab; if current tab is empty, it loads there
- **Multiple file select**: the open dialog now accepts multiple files — each opens in its own tab
- **Tab close button (×)**: closes the tab; prompts to save if modified; last tab clears content instead of closing
- **File → Close Tab** (Ctrl+W): same behaviour as the × button
- **Window close**: checks all modified tabs before quitting — prompts per tab
- Each tab maintains its own canvas, thumbnail panel, undo/redo history, and document state
- Tab title shows filename + ` *` when unsaved changes are present

### Lighter Icon Style

- Icons that have a regular (outline) variant in Font Awesome 6 switched from solid (`fa6s`) to regular (`fa6.`): folder-open, floppy-disk, share-from-square, circle-xmark, clipboard, object-group, file, image, pen-to-square, square, hand, trash-can
- Icon color lightened from `#444444` to `#888888` across all icons

---

## Files Modified

| File | Description |
|------|-------------|
| `ui/mainwindow.py` | Tab widget, `_TabState` dataclass, tab management methods, property accessors, icon updates |
| `VERSION` | Bumped to 0.4.0 |

---

# Version Notes - PDFTool v0.3.0

**Release Date**: 2026-04-24

## Summary

This release adds PDF encryption support with AES-256 and permission enforcement. Documents can be saved with owner and optional open passwords. PDFTOOL now respects PDF permission flags on open — restricted documents lock all editing tools automatically, with an unlock flow via owner password.

---

## New Features

### PDF Encryption (`Document → Encrypt / Set Password…`)
- Save encrypted copy with AES-256 (`fitz.PDF_ENCRYPT_AES_256`)
- **Owner password** (required): controls who can override restrictions
- **User password** (optional): required to open the file
- **Permission checkboxes**: printing, copy text, modify, annotate/forms
- Saves to a new file — current open document unchanged

### Permission Enforcement on Open
- On load, `doc.permissions` bitmask is checked
- If modify/annotate not allowed: all editing tools disabled (select, text, images, annotations, page ops, signatures, properties, undo/redo)
- Canvas forced to pan-only mode when restricted
- Status bar shows 🔒 when document is read-only

### Password Prompt for Encrypted Files
- Files with user password now prompt on open
- Wrong password = document does not open

### Unlock for Editing (`Document → Unlock for Editing…`)
- Prompts for owner password
- Correct password re-enables all tools for the session

### Bug Fix: Permission Detection
- Fixed: `perms < 0` incorrectly treated all encrypted PDFs as owner-unlocked (PDF spec sets high bits, making value always negative)
- Correct check: `perms == -4` (PyMuPDF value after owner authentication)

---

## Files Modified

| File | Description |
|------|-------------|
| `ui/encrypt_dialog.py` | New — password + permissions dialog |
| `ui/mainwindow.py` | Encrypt/unlock actions, permission enforcement, password prompt on open |

---

# Version Notes - PDFTool v0.2.0

**Release Date**: 2026-04-23

## Summary

This release introduces comprehensive code quality improvements, page manipulation features, advanced selection tools, and Trilium Notes integration. The application now supports adding, deleting, and reordering PDF pages, rectangle-based selection with directional modes, along with full undo/redo support for all page operations.

---

## Code Quality Improvements

### Project Configuration
- **Added `pyproject.toml`**: Modern Python packaging with project metadata, dependencies, and tool configurations
  - Build system configuration using setuptools
  - Project scripts entry point for `pdftool` command
  - Development dependencies: pytest, pytest-qt, ruff, mypy
  - Ruff linting configuration (line-length: 100, Python 3.10+ target)
  - MyPy type checking configuration with strict settings
  - Pytest configuration with PyQt6 API support

### Documentation
- **Created `README.md`**: Comprehensive project documentation
  - Installation instructions with system dependencies
  - Feature overview with keyboard shortcuts
  - Development guide with code quality tools
  - Project structure explanation
  - Architecture overview (Command pattern, Tool system, Document model)
  - Troubleshooting section

### Core Improvements

#### `core/document.py`
- Added comprehensive docstrings to all public methods
- Added logging throughout (replacing silent exception handling)
- Added `@lru_cache` to `_find_unicode_font()` for performance optimization
- Added `fitz_doc` property for read-only access to underlying document
- **New Methods**:
  - `insert_blank_page(index, width, height)`: Insert blank page at specified index
  - `delete_page(index)`: Delete page at specified index
  - `move_page(from_index, to_index)`: Move page between positions
  - `get_page_size(page_num)`: Get page dimensions as (width, height) tuple

#### `core/history.py`
- **New Commands**:
  - `InsertPageCmd`: Insert blank page with undo support
  - `DeletePageCmd`: Delete page with full page content preservation for undo
  - `MovePageCmd`: Move page between positions with undo support
- Enhanced `undo()` and `redo()` methods to handle page operations (return -1 for page ops)

#### `main.py`
- Added logging configuration with basic formatting
- Improved `_read_version()` with better error handling and docstrings
- Added proper exception handling for VERSION file reading

### UI Improvements

#### `ui/mainwindow.py`
- Fixed import ordering (moved mid-file imports to top)
- Added PDF file type validation in `_load_path()` method
- Added PIL image validation before processing in `_start_image_insert()`
- Removed `_Path` alias inconsistency, using standard `Path` throughout
- Added logging support
- **New Page Operations**:
  - Added `_on_insert_page_toolbar()` method for toolbar button
  - Added `_on_page_insert()` method for inserting pages
  - Added `_on_page_delete()` method with confirmation dialog
  - Added `_on_page_move()` method for drag-and-drop reordering
  - Updated `_undo()` and `_redo()` to handle page structure changes
- Added "Insert Page" toolbar button with icon and shortcut (Ctrl+Shift+N)
- Connected page manipulation signals from thumbnail panel

#### `ui/thumbnail_panel.py`
- **Major Refactoring** for drag-and-drop support:
  - Enabled `InternalMove` drag-drop mode
  - Added `rowsMoved` signal handler for reordering
  - Added context menu with right-click support
  - Added custom signals: `page_move_requested`, `page_delete_requested`, `page_insert_requested`
- **New Methods**:
  - `_on_rows_moved()`: Handle drag-and-drop page reordering
  - `_on_context_menu()`: Show context menu for page operations
  - `refresh_thumbnails()`: Refresh all thumbnails after structural changes
  - `insert_thumbnail()`: Insert single thumbnail at index
  - `remove_thumbnail()`: Remove single thumbnail at index
- Fixed `QSize` import (was using awkward `__class__` construction)
- Added logging support

#### `ui/canvas.py`
- Extracted magic numbers to named constants:
  - `PAGE_GAP = 20`: Pixels between pages
  - `SCENE_MARGIN = 10`: Margin around content
  - `RENDER_SCALE = 2.0`: Base render DPI multiplier
  - `MIN_RENDER_SCALE = 1.0`: Minimum render scale
  - `MAX_RENDER_SCALE = 5.0`: Maximum render scale
  - `RENDER_SCALE_THRESHOLD = 0.30`: Re-render threshold (30% change)
  - `ZOOM_IN_FACTOR = 1.25`: Zoom in multiplier
  - `ZOOM_OUT_FACTOR = 0.8`: Zoom out multiplier
  - `WHEEL_ZOOM_FACTOR = 1.15`: Mouse wheel zoom factor
  - `FIT_WIDTH_MARGIN = 20`: Margin when fitting to width
  - `TEXT_WRITER_SCALE_FACTOR = 1.5`: Scale factor for TextWriter

---

## New Features

### Page Manipulation

#### Insert Blank Pages
- **Toolbar Button**: New "Insert Page" button adds page after current page
- **Keyboard Shortcut**: `Ctrl+Shift+N` to insert page
- **Context Menu**: Right-click on thumbnail → "Insert page before/after"
- **Format Matching**: New pages automatically match dimensions of first existing page (or A4 default)

#### Delete Pages
- **Context Menu**: Right-click on thumbnail → "Delete page"
- **Confirmation Dialog**: Asks for confirmation before permanent deletion
- **Undo Support**: Full undo capability with page content restoration

#### Drag-and-Drop Reordering
- **Visual Interface**: Click and drag thumbnails to reorder pages
- **Real-time Feedback**: Thumbnails move during drag operation
- **Undo Support**: Move operations are fully undoable

### Rectangle Selection Tool

#### Directional Selection Modes
- **Drag Top-Down (↓)**: Select objects **completely inside** the rectangle
  - Blue highlight color indicates "inside" mode
  - Only objects fully contained within the selection rectangle are selected
- **Drag Bottom-Up (↑)**: Select objects that **intersect or touch** the rectangle
  - Orange highlight color indicates "intersect" mode
  - Objects that overlap or touch the selection boundary are selected

#### Features
- **New Toolbar Button**: Rectangle Select tool located next to Single Select tool
- **Multi-Object Selection**: Can select annotations, images, drawings, and text spans simultaneously
- **Visual Feedback**: Rubber band rectangle with color-coded selection mode
- **Auto-Activation**: After selection, automatically switches to Select tool with selected object(s)

#### Technical Implementation
- **File**: `tools/rect_select.py`
- **Class**: `RectangleSelectTool` extends `AbstractTool`
- Hit detection for: annotations, images, vector drawings, text spans
- Selection modes: `inside` (contains) vs `intersect` (overlaps/touches)

### Keyboard Shortcuts Added

| Shortcut               | Action                             |
| ------------------------| ------------------------------------|
| `Ctrl+Shift+N`         | Insert new page after current page |
| `[`                    | Send selected image to back        |
| `]`                    | Bring selected image to front      |
| `Delete` / `Backspace` | Delete selected object             |
| `Escape`               | Cancel current tool                |

---

## Architecture Changes

### Command Pattern Extension
The undo/redo system now supports page-level operations alongside content operations:

- **Content Commands**: `AddAnnotCmd`, `MoveTextCmd`, `EditTextCmd`, `AddTextCmd`, `DeleteAnnotCmd`, `MoveAnnotCmd`
- **Page Commands**: `InsertPageCmd`, `DeletePageCmd`, `MovePageCmd`

Page commands return `-1` from `undo()`/`redo()` to signal full document reload needed.

### Document Model Enhancement
`PDFDocument` now provides full page manipulation API:
- Page insertion with automatic format detection
- Page deletion with content preservation for undo
- Page movement with position tracking
- Page size queries for format matching

---

## Dependencies

### Added to `requirements.txt` / `pyproject.toml`
```
PyQt6>=6.4
pymupdf>=1.23
Pillow>=10.0
qtawesome>=1.3
```

### Development Dependencies
```
pytest>=7.0
pytest-qt>=4.2
ruff>=0.1.0
mypy>=1.0
```

---

## System Requirements

- **Python**: 3.10 or higher
- **OS**: Linux (primary), macOS and Windows compatible
- **System Dependencies**: fontconfig (for font detection)

---

## Files Modified

| File | Lines Changed | Description |
|------|---------------|-------------|
| `pyproject.toml` | +95 (new) | Project configuration, dependencies, tool settings |
| `README.md` | +214 (new) | Comprehensive documentation |
| `core/document.py` | +120/-10 | Page operations, logging, docstrings, caching |
| `core/history.py` | +60/-4 | Page command classes, undo/redo enhancements |
| `main.py` | +15/-5 | Logging, improved version reading |
| `ui/mainwindow.py` | +110/-15 | Page operations, toolbar button, signals |
| `ui/thumbnail_panel.py` | +95/-25 | Drag-and-drop, context menu, signals |
| `ui/canvas.py` | +25/-10 | Constants extraction, magic numbers removal |

---

## Backward Compatibility

This release maintains full backward compatibility. All existing features continue to work as before, with new features being purely additive.

---

## Known Limitations

- **Delete Page Undo**: Stores full page content in memory for undo, which may be memory-intensive for large documents with many pages
- **Thumbnail Rendering**: All thumbnails rendered upfront; large documents may experience slower initial loading

---

## Future Roadmap

Potential enhancements for future versions:
- Lazy-loaded thumbnails for large documents
- Page rotation support
- Page merging/splitting
- Batch page operations
- Custom page sizes in UI

---
