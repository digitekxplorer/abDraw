# abDraw

**A schematic-capture and diagramming package for electronic diagrams, written in pure Python with Tkinter.**

abDraw began as a general-purpose vector drawing tool and has grown into a full
**electronic-schematic capture** application. It supports named pins, schematic
primitives, buses and bit-slices, multi-sheet design packages, an orthogonal wire
auto-router, netlist generation, design-rule checking, and PNG/PDF export — while
keeping all of its original freehand drawing capabilities. Its goal target is
recreating CPU-datapath schematics such as the 16-bit **abCore16** CPU core.

No external EDA tooling required — abDraw runs anywhere Python and Tkinter run.

---

## Features

### Schematic capture
- **Named pins / ports** — pins on block edges (L/R/T/B), ordered and grid-aligned.
  Wires bind to a specific named pin and stay attached through moves and resizes.
  Bulk-add numbered pin ranges (e.g. `io1`…`io16`) with optional zero-padding,
  skipping any names that already exist.
- **Primitives** — multiplexer (binary-labeled inputs, `sel` + `y`), register
  (D/Q/clk with clock triangle), adder (`+` glyph), and rotatable off-page connector.
- **Buses & bit-slices** — thick bus wires, bit-slice taps (e.g. `[7:0]`), and
  automatic junction dots where three or more wire ends coincide.
- **Net labels & off-page connectors** — same net name = same net; same connector
  name = same node across sheets.
- **Orthogonal auto-router** — wires enter and exit each pin perpendicular to its
  edge and reroute automatically as blocks move, with staggered approaches so
  parallel risers don't overlap. Manual waypoint editing is fully supported.
- **Multi-sheet packages** — sheet tabs (add / rename / delete / reorder / switch),
  per-sheet title block, and per-sheet page sizes (Letter, Legal, Tabloid, ANSI,
  A-series, Custom) on a scrollable page + pasteboard canvas. Reordering keeps the
  moved sheet active and renumbers each sheet's title block automatically.
- **Netlist & DRC** — generate a `.net` netlist (union-find across all sheets) and
  validate the schematic, flagging unconnected pins.

### Drawing & annotation
- **Shape tools** — Select, Line, Arrow, Rectangle, Square, Circle, Ellipse,
  Triangle, with adjustable thickness, stroke color, and grid snapping.
- **Group selection** — marquee-drag to select multiple shapes, move them together
  (pinned wires stay coherent), and delete them as a single undoable action.
- **Fill** — No Fill or a chosen fill color per shape. Interior text (pin names,
  adder glyph, connector names) **auto-contrasts** the fill so labels stay readable.
- **Note Arrow / Note Line** — non-electrical annotation arrow and line for pointing
  at or underlining a block from a caption; excluded from the netlist, DRC, and
  junction detection. Note Lines support named dash patterns (Solid, Dashed, Fine,
  Long, Dotted, Dash-dot) and adjustable width, which render on canvas and in export.
- **Text** — font, size, bold/italic, and left / center / right alignment.

### Files & export
- **JSON save/load** — v2 multi-sheet package format (legacy single-sheet files are
  auto-wrapped on open).
- **Export** — Sheet PNG, All-Sheets PNG, Sheet PDF, and multi-page Package PDF.
  Rendering is PIL-only (no Ghostscript) and honors each sheet's page size, fills,
  label contrast, and dragged label positions so exports match the screen.

---

## Requirements

- **Python 3.8+**
- **Tkinter** — bundled with most Python installs (`python -m tkinter` to verify;
  on Debian/Ubuntu: `sudo apt install python3-tk`)
- **Pillow** — for PNG/PDF export: `pip install Pillow`

## Getting started

```bash
git clone <your-repo-url>
cd abDraw
pip install Pillow
python main.py
```

## Project structure

| File | Responsibility |
|------|----------------|
| `main.py` | Entry point — creates the Tk root and launches the app. |
| `drawing_app.py` | Tk UI: toolbar, tools, menus, mouse handlers, selection, dialogs. |
| `canvas_manager.py` | Rendering, the orthogonal router, junctions, multi-sheet state, netlist. |
| `shapes.py` | `Shape` and `Port` data structures with JSON round-tripping. |
| `file_manager.py` | JSON save/load and the PIL-based PNG/PDF export engine. |
| `dialogs.py` | Tk dialog classes (label, sheet size, note style, pin range, port editor, special pins, text input). |

## Usage notes

- Pick a tool from the toolbar, then draw on the canvas. **Select** moves and edits
  existing shapes; drag a wire endpoint onto a pin to connect it.
- **Fill** applies to the selected shape and becomes the default for new shapes.
- Wires with a pinned end are owned by the auto-router. To route by hand, drag a
  wire's waypoint handles (double-click a segment to insert one); **Auto-Route Wire**
  resets a wire to automatic routing.
- Use **File → Export** for PNG/PDF output and **Generate Netlist** / **Validate
  Schematic** for connectivity checks.

## Roadmap ideas

- Cross-sheet undo/redo
- Full electrical-net highlight on click
- Lockable manual routes
- Manual waypoints that translate with a dragged block

## License

Released under the [MIT License](LICENSE).
