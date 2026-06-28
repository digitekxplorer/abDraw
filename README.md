# abDraw

A schematic-capture and diagramming application built entirely in **Python + Tkinter**. abDraw started as a general-purpose vector drawing tool and grew into a lightweight package for drawing real electronic schematics — named pins, primitives, auto-routed wires, multi-sheet packages, netlists, and PNG/PDF export — with no dependencies beyond Pillow.

## Features

- **Drawing tools** — line, arrow, rectangle, square, circle, ellipse, triangle, and text labels, with adjustable thickness, color, fill, and grid snapping.
- **Schematic primitives** — mux (binary-labeled inputs, `sel`/`y`), register (D/Q/clk with clock triangle), adder (`+` glyph), and rotatable off-page connectors.
- **Named pins / ports** — pins anchored to a block edge that wires bind to and stay attached through moves and resizes. Edit Pins… (`Ctrl+P`).
- **Special pins** — one-click standard control pins with fixed placement: `en`/`set` (top), `clr` (bottom), and an optional `clk` (left, with clock triangle) on shapes that lack one. Special Pins… (`Ctrl+Shift+P`).
- **Wires** — buses, bit-slice taps (e.g. `[7:0]`), automatic junction dots, net labels, and an **orthogonal auto-router** that keeps wires perpendicular to pins through every move, plus manual waypoint editing.
- **Multi-sheet packages** — sheet tabs, per-sheet title block and page size (Letter/Legal/Tabloid/ANSI/A-series/Custom), scrollable pasteboard.
- **Netlist & DRC** — cross-sheet netlist export (`.net`) and a validator that flags unconnected pins.
- **Export** — Sheet/All-Sheets PNG, Sheet PDF, and full multi-page Package PDF (PIL-only, no Ghostscript).
- **Editing** — 50-level undo/redo, copy/paste, z-order, and a JSON project format (human-readable, backward-compatible).

## Requirements

- Python 3.8+
- [Pillow](https://python-pillow.org/) — `pip install Pillow` (for PNG/PDF export)

Tkinter ships with the standard CPython installer on Windows and macOS; on Linux install `python3-tk`.

## Getting Started

```bash
pip install Pillow
python main.py
```

## Project Structure

| File | Responsibility |
|------|----------------|
| `main.py` | Entry point / app bootstrap |
| `shapes.py` | `Shape` & `Port` data classes, pin helpers, `STANDARD_PINS` |
| `canvas_manager.py` | Rendering, orthogonal router, junctions, netlist, multi-sheet state |
| `file_manager.py` | JSON save/load and the PIL PNG/PDF export engine |
| `drawing_app.py` | Tkinter UI — tools, menus, dialogs, sheet tabs |

## Keyboard Shortcuts

`Ctrl+N/O/S` new/open/save · `Ctrl+Z/Y` undo/redo · `Ctrl+C/V` copy/paste · `Ctrl+L` add label · `Ctrl+P` Edit Pins · `Ctrl+Shift+P` Special Pins · `Ctrl+B` toggle bus · `Ctrl+R` rotate connector · `Ctrl+G` toggle grid · `Ctrl+H` toggle snap

## License

_MIT License_

