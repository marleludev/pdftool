# PDFTool

A PyQt6-based desktop PDF editor built on PyMuPDF (fitz). Supports annotation, freehand drawing, text editing with font preservation, image insertion, page management, and full undo/redo.

## Features

### Document Management
- **Multi-tab**: open and edit multiple PDFs simultaneously; each tab has its own canvas, history, and tool state
- **Open / Save / Save As**: saves to a new `_edited` copy by default to preserve originals
- **Metadata editor**: view and edit PDF title, author, subject, keywords, producer fields
- **Encryption**: set or remove document password protection
- **Compression**: reduce file size by re-compressing page content streams
- **Prune**: strip unused objects, form fields, scripts, and thumbnails from the PDF
- **Scanned PDF export**: flatten pages to rasterised images for clean printing or archiving
- **Signature**: add handwritten or typed signatures from a dedicated dialog
- **Resize page**: change individual page dimensions with three content modes — scale, keep, crop

### Navigation
- **Multi-page canvas**: all pages rendered in a single scrollable view with configurable gap
- **Thumbnail panel**: left sidebar shows all pages; click to jump, drag to reorder pages
- **Fit to width**: auto-scale to viewport width
- **Zoom**: Ctrl+scroll wheel, Ctrl++/Ctrl+−, or toolbar buttons
- **Page indicator** in status bar; updates as you scroll

### Tools

#### Select Tool (single object)
- Click any annotation, image, vector drawing, or text span to select it
- Drag to move the selected object; undo/redo supported for all types
- Delete / Backspace to remove the selected object
- Images show resize handles at corners (Shift = proportional resize)
- Z-order controls to send images to back or bring to front

#### Rectangle Select Tool (multiple objects)
- Drag **top→bottom** (blue tint): selects objects **completely inside** the rectangle
- Drag **bottom→top** (orange tint): selects objects **intersecting** the rectangle
- Hands off to MultiSelectTool — all selected objects highlighted and can be moved or deleted as a group

#### Text Add Tool
- Click anywhere on the page to open an inline text editor
- Enter to commit, Shift+Enter for newline, Escape to cancel
- Text committed using Helvetica 12pt by default

#### Text Edit Tool
- Click any existing text span to open the Edit dialog
- **Font combo** pre-populated with the span's current font name so re-saving preserves appearance
- Font resolved in priority order: embedded font bytes → built-in PDF font → system font via fc-match
- PostScript font names (e.g. `CourierNewPS-BoldMT`, `NimbusMonoPS-Regular`) automatically mapped to correct built-in fitz equivalents, preserving bold/italic style
- Change font to any built-in (Helvetica, Times, Courier and their bold/italic variants), or pick any system font via the font picker (TTF/OTF only)
- Change size, color; undo/redo supported

#### Brush / Pen Tool
- **Styles**: Pen (1.5 pt), Brush (3.5 pt, 85% opacity), Marker (10 pt, 35% opacity)
- **Smoothness**: Normal, Smooth, Very Smooth — controls Ramer-Douglas-Peucker simplification epsilon and Chaikin corner-cutting iterations
- **Close path**: checkbox in the drop-down menu; when checked the path is smoothed as a closed loop (no sharp joint between last and first point) and the ink stroke closes back to start
- Color picker: Black, Blue, Red, Green, Purple
- Undo/redo supported; stroke is stored as an ink annotation

#### Encircle Tool (closed freehand shape)
- Draws a freehand closed polygon annotation (stored as a PDF Polygon annotation)
- Full Chaikin closed-loop smoothing: last→first joint smoothed equally with all other joints
- Color picker; configurable stroke width
- Undo/redo supported

#### Highlight Tool
- Drag to highlight a rectangular area with a configurable color
- Stored as a PDF Highlight annotation

#### Rectangle Annotation Tool
- Drag to draw a red rectangle annotation (1.5 pt border)
- Stored as a PDF Square annotation

#### Image Insert Tool
- Insert from file (PNG, JPEG, BMP, etc.) or paste from clipboard (Ctrl+V)
- Click to place at natural size; drag resize handles after placing

### Page Operations (all undoable)
- **Insert page**: before or after any page, matching the nearest page dimensions
- **Delete page**: with undo that restores full page content
- **Move/reorder pages**: drag thumbnails in the sidebar
- **Rotate page**: 90° clockwise/counterclockwise from the Page menu
- **Resize page**: scale content, keep content at original coords, or crop

### Undo / Redo
Full command-pattern history (up to 500 steps). Covered operations:
- Add / delete / move annotations (Highlight, Square, Polygon, Ink)
- Add / move text
- Edit text (content, font, size, color) with font bytes preserved for re-embedding
- Move / resize images
- Move vector drawings
- Insert / delete / move / rotate / resize pages

Not yet covered (direct page modifications with no undo): delete drawing, delete text, delete image, image resize from select tool.

---

## Installation

### Requirements
- Python 3.10+
- Linux (primary target); macOS and Windows may work

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### System Dependencies

fontconfig is required for font detection (`fc-match`):

```bash
# Debian/Ubuntu
sudo apt-get install fontconfig

# Fedora/RHEL
sudo dnf install fontconfig

# Arch
sudo pacman -S fontconfig
```

---

## Usage

```bash
python main.py
```

### Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+O` | Open PDF |
| `Ctrl+S` | Save (`_edited` copy) |
| `Ctrl+Shift+S` | Save As |
| `Ctrl+W` | Close current tab |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` | Redo |
| `Ctrl+Shift+N` | Insert blank page after current |
| `Ctrl+V` | Paste image from clipboard |
| `Ctrl+Shift+I` | Insert image from file |
| `Ctrl++` | Zoom in |
| `Ctrl+−` | Zoom out |
| `Ctrl+0` | Fit to width |
| `[` | Send selected image to back |
| `]` | Bring selected image to front |
| `Delete` / `Backspace` | Delete selected object(s) |
| `Escape` | Cancel current tool / clear selection |

---

## Project Structure

```
pdftool/
├── core/
│   ├── document.py          # PDFDocument — PyMuPDF wrapper; font resolution, text/image/annotation ops
│   └── history.py           # Command pattern (execute/undo); History stack; all concrete commands
├── tools/
│   ├── base.py              # AbstractTool — on_press/on_move/on_release/on_key/cancel interface
│   ├── annotate.py          # HighlightTool, RectAnnotateTool
│   ├── brush.py             # BrushTool (ink), EncircleTool (polygon); path smoothing algorithms
│   ├── image_insert.py      # ImageInsertTool — click-to-place
│   ├── select.py            # SelectTool — hit-test, drag-move, resize; handles all object types
│   ├── rect_select.py       # RectangleSelectTool — area select, two modes (inside/intersect)
│   ├── multi_select.py      # MultiSelectTool — move/delete a set of objects as a group
│   ├── text_add.py          # TextAddTool — inline QGraphicsTextItem editor
│   ├── text_edit.py         # TextEditTool + TextEditDialog — edit existing PDF text spans
│   └── _drawing_surgery.py  # strip_drawing() — token-level PDF stream parser to remove a vector path
├── ui/
│   ├── canvas.py            # PDFCanvas (QGraphicsView) — renders pages, routes tool events, zoom
│   ├── mainwindow.py        # MainWindow — toolbar, menus, tab widget, tool wiring
│   ├── thumbnail_panel.py   # ThumbnailPanel — drag-to-reorder sidebar
│   ├── properties_dialog.py # PDF metadata editor dialog
│   ├── compress_dialog.py   # Compression options dialog
│   ├── encrypt_dialog.py    # Password encryption dialog
│   ├── prune_dialog.py      # Object pruning dialog
│   ├── resize_page_dialog.py# Page resize dialog
│   └── signature_dialog.py  # Signature capture/insert dialog
└── main.py                  # Entry point; version read; icon-theme setup for frozen bundles
```

---

## Architecture

### Command Pattern (undo/redo)

Every user action that modifies the PDF is encapsulated in a `Command` subclass with `execute()` and `undo()`. `History` maintains an undo stack and a redo stack (capped at 500 entries). Pushing a new command clears the redo stack.

Page-level commands (insert/delete/move/rotate/resize) snapshot the affected page as a complete PDF sub-document so they can be restored exactly.

Content commands (text, annotation, image, drawing) update the live `fitz.Document` in-place and track enough state (original bbox, font bytes, annotation snapshot, drawing dict) to reverse the operation.

Annotation move uses delete+recreate rather than in-place update because `fitz.Annot` caches its data at load time — writing to the xref directly and then calling `annot.update()` regenerates the appearance from stale cached values.

### Font Resolution (`_resolve_font` / `_builtin_for_name`)

Priority order when inserting or editing text:
1. **Embedded font bytes** (`fitz.Font(fontbuffer=...)`) — preserves exact original typeface
2. **Built-in fitz font** mapped from the span's font name — handles standard PDF fonts (Helvetica, Times, Courier) and PostScript variant names (CourierNewPS-BoldMT, NimbusMonoPS-Regular, ArialMT, etc.) by stripping PS/MT/OT markers and detecting bold/italic keywords separately
3. **System font** via `fc-match` — last resort for non-standard faces
4. **Helvetica** (`helv`) — ultimate fallback

### Path Smoothing (Brush / Encircle)

1. Raw mouse points are simplified with **Ramer-Douglas-Peucker** (removes near-collinear points)
2. Smoothed with **Chaikin corner-cutting** (iterative subdivision)

Two Chaikin variants:
- `_chaikin` (open path): first and last points are fixed
- `_chaikin_closed` (closed path): all joints treated equally by wrapping last→first via modular index — used by both EncircleTool and BrushTool when "Close path" is checked

### Drawing Surgery (`_drawing_surgery.py`)

`strip_drawing()` removes a single vector path from a PDF content stream without touching the rest of the page. It tokenises the raw stream bytes, tracks `q`/`Q` graphics-state groups, finds the path whose bounding box matches the target, and splices out the byte range. If the enclosing `q…Q` group contains only that one painted path, the entire group (including graphics-state setup) is removed.

---

## Development

```bash
# lint + format
ruff check . && ruff format .

# type check
mypy .

# tests
pytest
```
