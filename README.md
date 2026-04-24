# PDFTool

A PyQt6-based PDF editor with annotation, text editing, and image insertion capabilities.

## Features

- **Document Viewing**: Multi-page PDF viewer with thumbnail panel
- **Page Manipulation": 
  - Add new blank pages (matching existing page format)
  - Delete pages
  - Reorder pages via drag-and-drop in thumbnail panel
- **Annotations**: Highlight and rectangle annotations
- **Selection Tools**: 
  - Single click selection for move/delete
  - Rectangle selection with two modes: drag down (select inside) or drag up (select intersecting)
- **Text Editing**: Add, edit, and move text within PDFs
- **Image Insertion**: Insert images from files or clipboard
- **Page Management**: Navigate pages, fit-to-width zoom
- **Undo/Redo**: Full command history for all operations
- **Document Properties**: Edit PDF metadata
- **Export Options**: Convert to scanned PDF, prune unused objects
- **Modern Icons**: All toolbar buttons, menus, and dialogs use Material Design Icons (via qtawesome)

## Installation

### Requirements

- Python 3.10 or higher
- Linux (primary target), macOS and Windows may work

### Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/pdftool.git
cd pdftool

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Or install with development dependencies
pip install -e ".[dev]"
```

### System Dependencies

On Linux, ensure you have fontconfig installed for font detection:

```bash
# Debian/Ubuntu
sudo apt-get install fontconfig

# Fedora/RHEL
sudo dnf install fontconfig

# Arch
sudo pacman -S fontconfig
```

## Usage

### Running the Application

```bash
python main.py
```

Or if installed via pip:

```bash
pdftool
```

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+O` | Open PDF |
| `Ctrl+S` | Save (creates `_edited` copy) |
| `Ctrl+Shift+S` | Save As |
| `Ctrl+W` | Close document |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` | Redo |
| `Ctrl+Shift+N` | Insert new page after current page |
| `Ctrl+V` | Paste image from clipboard |
| `Ctrl+Shift+I` | Insert image from file |
| `Ctrl++` | Zoom in |
| `Ctrl+-` | Zoom out |
| `Ctrl+0` | Fit to width |
| `[` | Send selected image to back |
| `]` | Bring selected image to front |
| `Delete` / `Backspace` | Delete selected object(s) |
| `Escape` | Cancel current tool |

**Selection Tools:**
- **Single Select Tool** (cursor icon): Click to select individual objects
- **Rectangle Select Tool** (selection-drag icon): 
  - Drag **downwards** (top to bottom): Select objects **completely inside** the rectangle
  - Drag **upwards** (bottom to top): Select objects that **intersect or touch** the rectangle
  - Selects **multiple objects** at once - all matching objects are highlighted
  - **Multi-Select Mode**: After rectangle selection, all selected objects are shown with blue highlight boxes
  - **Drag to move**: Click and drag any selected object to move all selected objects together
  - **Delete All**: Press `Delete` to remove all selected objects at once

**Page Sidebar (Right-click on thumbnail):
- **Insert page before**: Add new blank page before selected page
- **Insert page after**: Add new blank page after selected page
- **Delete page**: Remove the selected page
- **Drag-and-drop**: Reorder pages by dragging thumbnails

## Development

### Code Quality

This project uses:

- **ruff**: Linting and formatting
- **mypy**: Static type checking
- **pytest**: Testing framework

### Running Checks

```bash
# Format code
ruff format .

# Run linter
ruff check .

# Run type checker
mypy .

# Run tests
pytest
```

### Project Structure

```
pdftool/
├── core/
│   ├── __init__.py
│   ├── document.py      # PDFDocument wrapper around PyMuPDF
│   └── history.py       # Command pattern for undo/redo
├── tools/
│   ├── __init__.py
│   ├── base.py          # AbstractTool base class
│   ├── annotate.py      # Highlight and rectangle tools
│   ├── image_insert.py  # Image insertion tool
│   ├── select.py        # Selection and move tool
│   ├── text_add.py      # Text addition tool
│   ├── text_edit.py     # Text editing tool
│   └── _drawing_surgery.py  # Drawing manipulation utilities
├── ui/
│   ├── __init__.py
│   ├── mainwindow.py    # Main application window
│   ├── canvas.py        # PDF rendering canvas
│   ├── thumbnail_panel.py  # Page thumbnail sidebar
│   ├── properties_dialog.py  # Document metadata dialog
│   ├── signature_dialog.py   # Signature management dialog
│   └── prune_dialog.py   # Document pruning dialog
├── main.py              # Application entry point
├── pyproject.toml       # Project configuration
└── requirements.txt     # Dependencies
```

## Architecture

### Command Pattern for Undo/Redo

The application uses the Command pattern to implement undo/redo functionality:

- `Command` abstract base class defines `execute()` and `undo()` methods
- `History` class manages undo/redo stacks
- Concrete commands encapsulate operations:
  - Content commands: `AddAnnotCmd`, `MoveTextCmd`, `EditTextCmd`
  - Page commands: `InsertPageCmd`, `DeletePageCmd`, `MovePageCmd`

### Tool System

Tools inherit from `AbstractTool` and implement:

- `on_press()`: Mouse press handling
- `on_move()`: Mouse move handling
- `on_release()`: Mouse release handling
- `on_key()`: Keyboard event handling
- `cancel()`: Cleanup when tool is deselected

### Document Model

`PDFDocument` wraps `fitz.Document` (PyMuPDF) and provides:

- Page rendering at variable scales
- Annotation operations (add/delete)
- Text operations (insert/edit/move)
- Font resolution (builtin, embedded, system)

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run the code quality checks
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## Troubleshooting

### Fonts not rendering correctly

The application tries to find a Unicode-capable font using `fc-match`. Ensure fontconfig is installed and configured.

### Icons not showing

The application first tries to use system theme icons via `QIcon.fromTheme()`, then falls back to qtawesome MDI icons. On Linux, ensure you have a compatible icon theme installed.

### Large PDFs are slow

The application renders all pages upfront for the thumbnail panel. For very large documents, this may be slow. Consider using a subset of pages for editing.
