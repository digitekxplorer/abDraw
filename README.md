# abDraw — Schematic Drawing Package

abDraw is a Tkinter-based **schematic drawing tool for electronic diagrams**, written in
Python. The user develops it in PyCharm and pastes updated files back here. Our job is to
extend/refactor the Python code. The goal target is recreating CPU-datapath schematics like
the two reference images in `uploads/` (a 16-bit CPU core, "abCore16").

## Where the code lives

- **`uploads/abDraw_current/`** — the CURRENT canonical working version. Always read/edit
  these five files: `main.py`, `drawing_app.py`, `canvas_manager.py`, `shapes.py`,
  `file_manager.py`.
- `uploads/src06/` — a previous snapshot. Do not edit; reference only.
- `uploads/abCore16_code/` — an older snapshot (Phases 1–6). Do not edit; reference only.
- `uploads/abCore16_sch01.jpg`, `uploads/abCore16_sch02.jpg` — target schematic images.
- `abCore16 Schematic Preview.dc.html` — an early HTML mock of the target output (not the app).

### Editing gotcha (IMPORTANT)
The Python files use **CRLF line endings**, so the `str_replace_edit` tool often fails with
"old_str found 0 times". Use the `run_script` tool instead: read the file, do
`t = raw.split('\r\n').join('\n')`, apply `replaceText(t, find, replace)`, convert back with
`t.split('\n').join('\r\n')`, and `saveFile`. This pattern has been reliable all along.
Python files can't be attached directly (use .txt/zip), and Tkinter can't run in this
environment — verify by reading code + grep, not by launching the app.

## Architecture

- **`shapes.py`** — `Shape` dataclass (one class for every shape type, JSON round-trips via
  `to_dict`/`from_dict`). `Port` dataclass. Module helpers: `make_primitive_ports`,
  `binary_labels`, `edge_positions`, `set_port_grid`, `port_lead_length`, `PORT_OUTWARD`.
  `Shape.port_anchor(name)` computes a pin's absolute position from current bounds.
- **`canvas_manager.py`** — rendering (`draw_shape`, `draw_ports`, `draw_wire_deco`),
  the orthogonal **router** (`_approach_point`, `ortho_points`, `_side_channel`,
  `_resolve_pin`, `_honor_waypoints`), junction detection (`compute_junctions`),
  multi-sheet state, title block, netlist (`build_netlist`), and the image export source
  geometry. Holds the LIVE active sheet in `self.shapes`; other sheets serialized in
  `self.sheets`.
- **`drawing_app.py`** — the Tk UI: toolbar/tools, menus, mouse handlers, selection,
  waypoint editing, sheet tabs, all the dialogs.
- **`file_manager.py`** — JSON save/load (v2 multi-sheet package, legacy single-sheet
  auto-wrapped), and the PIL-based PNG/PDF export engine (`render_sheet_image` + `_img_*`).
- **`main.py`** — entry point.

## Completed work (Phases 1–6 + polish)

1. **Ports/pins** — named pins on block edges (side L/R/T/B, ordered, grid-aligned). Wires
   bind to a specific named pin and stay attached through moves/resizes. Edit Pins… (Ctrl+P).
2. **Primitives** — `mux` (trapezoid, N inputs prompt, binary-labeled, `sel`+`y`),
   `register` (D/Q/clk with clock triangle), `adder` (+ glyph), off-page `connector`
   (named circle, rotatable attach side Ctrl+R).
3. **Wire features** — buses (Ctrl+B, thicker), bit-slice taps (e.g. `[7:0]`), junction dots
   (3+ ends coincide, or T-junction onto a segment).
4. **Net labels + off-page connectors** — same net_name = same net (blue, halo on select);
   same conn_name = same node across sheets.
5. **Multi-sheet package** — sheet tabs (add/rename/delete/switch), per-sheet title block
   ("Sheet N of M", date), per-sheet page sizes (Letter/Legal/Tabloid/ANSI/A-series/Custom),
   scrollable canvas with gray pasteboard + white page. v2 JSON package format.
6. **Netlist + DRC** — `build_netlist` (union-find across all sheets), Generate Netlist… (.net),
   Validate Schematic (rings unconnected pins red).
- **Export** — File→Export: Sheet/All-Sheets PNG, Sheet PDF, Package multi-page PDF.
  PIL-only (no Ghostscript); reuses canvas geometry; honors per-sheet page size.

## Recent updates (June 30, 2026)

- **Shape fill** — toolbar **Fill** button (No Fill / Choose Color…); applies to the
  selected fillable shape and sets the default for new ones. `current_fill` on the app,
  `FILLABLE_TYPES` set in `drawing_app.py`. Interior text (pin names, adder `+`, connector
  names) auto-contrasts the fill via `CanvasManager.label_color_for(shape)` (luminance from
  `winfo_rgb`); the PNG/PDF export calls the same helper so it matches the screen.
- **Note Arrow** — non-electrical annotation arrow. New `annotation: bool` field on `Shape`;
  tool name `annotation_arrow` builds a `shape_type="arrow"` with `annotation=True`. It never
  auto-binds (`_auto_connect_endpoints` early-returns), its endpoint drags snap to grid only
  (guards in on_drag/on_release), and it's excluded from `build_netlist`, `compute_junctions`,
  and DRC. Looks identical to a normal arrow.
- **Text alignment** — `text_align` (left/center/right) is now wired up: the Text dialog has
  an Align radio row; canvas maps it to anchor + `justify`; export mirrors it with the Pillow
  anchor + multiline `align` (`_text` gained an `align=` arg).
- **Export fix** — net-label and bit-slice-tap positions in `_img_wire` now reuse the
  canvas helpers (`net_label_base_point`/`net_label_offset`, `slice_tap_point`/
  `slice_label_offset`) so dragged labels export where the user placed them (was using the
  default offset).
- **Cleanup** — sheet-size menu callbacks use `functools.partial` instead of a
  loop-variable-default lambda (cleared a PyCharm unresolved-reference warning).

## The orthogonal routing scheme (most-iterated area — understand before touching)

General rule: **any wire with a pinned end is owned by the auto-router** and rebuilt from
endpoints + perpendicular staggered approaches on every component move, so wires always
enter/exit a pin **perpendicular to its edge** regardless of move direction.

- `_approach_point(wire, endpoint)` returns guide point(s) just outside a pin:
  `[tip]` (single perpendicular escape) for a lone wire on a side or a both-ends-pinned wire;
  `[corner, tip]` (staggered) when 2+ wires share a side, each in a distinct channel so
  risers don't overlap. Off-page connectors route as plain terminals (return None).
- `_resolve_pin` finds the bound pin even if `port_name` wasn't stored (nearest-pin fallback).
  `_end_has_pin_approach` mirrors this so BOTH ends of a wire are classified consistently
  (fixes the old zigzag where one end took a reaching "clean elbow").
- Direction-aware ordering + hysteresis (`_hyst`) keep fans from crossing/flip-flopping as a
  block passes level with its source.
- **Manual routing**: `_honor_waypoints` — `user_routed` (user dragged/inserted a waypoint)
  is always honored; a soft `manual_route` (drawn with click-bends) is honored **as drawn**
  and only released to the auto-router when a connected component **moves** (so a freshly
  placed waypoint never jumps on right-click-finish). Waypoint editing: drag blue handles,
  double-click to insert, orange segment handle slides a mid-segment; "Auto-Route Wire" resets.
- Mux T/B pins ride the **slanted** trapezoid edge (computed from `inset` + pin's fractional x),
  not the bounding box, so `sel` sits on the edge.

## Known minor limitation (user declined the fix — do NOT fix unless asked)

**Unfilled rectangle/square interiors aren't clickable.** `handle_selection`
(drawing_app.py ~line 1217) selects via `find_overlapping`, which only reports an unfilled
shape when the click box touches its *border* — so a click in the hollow interior misses
(clicking the outline works; filled shapes work everywhere). Confirmed real but minor; the
user is fine selecting by the border and explicitly declined a fix. If ever asked: in
`handle_selection`, fall back to a point-in-bounds test for closed shapes when
`find_overlapping` returns nothing, or give shapes a near-transparent fill for hit-testing.

## Parked enhancement ideas (not started; ask before building)

- Cross-sheet undo/redo (currently undo history clears on sheet switch).
- Full electrical-net highlight on click (beyond net-label/connector-name halo).
- Right-click "Lock manual route" toggle (pin a hand route without dragging a handle).
- Manual waypoints that translate with a dragged block (instead of full reroute).

## Working style with this user

Small, surgical edits — change only what's asked, preserve everything else. After each change:
name which file(s) to update in PyCharm, and give a short manual test script (no app launch
here). The user often supplies PNG exports to show routing problems; read them carefully.
Offer a zip download of `uploads/src06/` when they're about to take a break.
