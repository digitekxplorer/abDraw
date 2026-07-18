# ============================================================================
# FILE: canvas_manager.py
# ============================================================================
"""
Canvas operations and shape management.

This module currently has THREE responsibilities (candidate for a future
split; see CLAUDE.md "structural improvements"):

  1. RENDERING   — draw_shape / draw_ports / draw_wire_deco, highlights,
                   junction dots, DRC rings, title block.
  2. THE ROUTER  — the orthogonal wire auto-router (see map below).
  3. DOCUMENT    — sheets, undo/redo, clipboard, netlist, selection state.

========================  ORTHOGONAL ROUTER MAP  ========================

Ownership rule: ANY wire with a pinned end is owned by the auto-router and
is rebuilt from its endpoints on every connected-component move, so wires
always enter/exit a pin PERPENDICULAR to its edge. Manual routing is the
exception, gated by _honor_waypoints().

Entry points (called from outside the router):
  ortho_points(shape)        -> full drawn point list for an ortho wire,
                                including staggered pin approaches. THE
                                router entry; called by wire_polyline and
                                draw_shape.
  wire_polyline(shape)       -> drawn points for ANY wire type (straight
                                or ortho), deduplicated. Used by rendering,
                                junctions, hit-testing, net labels, export.
  update_connected_lines(s)  -> re-pins + reroutes every wire bound to a
                                moved/resized block.

Internals (call graph, top-down):
  ortho_points
    -> _honor_waypoints      manual-route gate: user_routed (dragged or
                             inserted a waypoint) is ALWAYS honored;
                             manual_route (click-bends while drawing) is
                             honored as drawn until a connected component
                             MOVES, then released to the auto-router.
    -> _approach_point       staggered turn point(s) just outside a pin:
                             [tip] for a lone wire / both-ends-pinned wire,
                             [corner, tip] when 2+ wires share a side.
                             Off-page connectors return None (plain
                             terminals).
       -> _resolve_pin       (side, port_name, anchor) for an endpoint;
                             falls back to nearest pin if port_name was
                             never stored.
       -> _side_channel      this endpoint's rank among all wires bound to
                             the same side of the target -> distinct
                             approach channels so risers don't overlap.
       -> _hyst              hysteretic comparisons so fan ordering doesn't
                             flip-flop as a block passes level with its
                             source.
    -> _end_has_pin_approach mirrors _approach_point's resolution so BOTH
                             ends of a wire are classified consistently
                             (prevents one-ended "clean elbow" zigzags).

Invariants (do not break):
  * A wire endpoint bound to a pin must leave that pin perpendicular to
    the pin's edge for at least the lead length.
  * Two wires bound to the same side of the same block must use distinct
    approach channels (no overlapping risers).
  * user_routed=True waypoints are never discarded by the router; only
    "Auto-Route Wire" (which clears the flag) releases them.
  * Mux T/B pins ride the SLANTED trapezoid edge (computed from inset +
    the pin's fractional x), not the bounding box.
  * wire_polyline is the single source of wire geometry for rendering,
    junctions, net labels, AND file_manager's PNG/PDF export — keep them
    in sync by changing geometry HERE, never in the consumers.
=========================================================================
"""
import tkinter as tk
import math
import datetime
import copy as _copy
from shapes import Shape, Connection, PORT_OUTWARD, port_lead_length

# All shape types that behave as connectable line segments
LINE_TYPES = ("line", "arrow", "ortho_line", "ortho_arrow")

# Named dash styles (Tk dash tuples; also used for PNG/PDF export). "solid" = no dash.
DASH_PATTERNS = {
    "solid":    (),
    "dashed":   (6, 4),
    "fine":     (3, 3),
    "long":     (12, 5),
    "dotted":   (2, 4),
    "dash-dot": (10, 4, 2, 4),
}
DASH_ORDER = ["solid", "dashed", "fine", "long", "dotted", "dash-dot"]
DASH_LABELS = {
    "solid": "Solid", "dashed": "Dashed", "fine": "Fine dash",
    "long": "Long dash", "dotted": "Dotted", "dash-dot": "Dash-dot",
}


def dash_tuple(shape):
    """Resolve a shape's dash pattern to a Tk/Pillow dash tuple.
    Falls back to the legacy `dashed` bool, then to solid."""
    pat = getattr(shape, "dash_pattern", "") or ""
    if not pat:
        pat = "dashed" if getattr(shape, "dashed", False) else "solid"
    return DASH_PATTERNS.get(pat, ())


class CanvasManager:
    """Manages canvas operations and shapes"""

    def __init__(self, app):
        self.app = app
        self.shapes = []
        self.next_shape_id = 1
        self.selected_shape = None
        self.selected_shapes = []   # group (marquee) selection — Phase A
        self.clipboard = None
        self.paste_count = 0   # cascades repeated Ctrl+V; reset on next copy
        self.undo_stack = []
        self.redo_stack = []
        self.max_undo = 50

        self.editing_endpoint = None
        self.drag_data = {"x": 0, "y": 0}
        self.temp_shape = None
        self.snap_distance = 15
        self.last_snap_port = None  # port name from the most recent get_snap_point
        self._route_state = {}  # hysteresis memory: route-decision key -> bool

        # Multi-sheet "drawing package". self.shapes / self.next_shape_id are
        # the LIVE active sheet; the other sheets live serialized in self.sheets
        # and are committed/loaded on switch. Each sheet record also carries
        # its own page size (width/height, in canvas pixel units).
        self.package_title = "Untitled"
        self.sheets = [{'name': 'Sheet 1', 'shapes': [], 'next_id': 1,
                        'width': 1700, 'height': 1100}]
        self.active_sheet = 0

    # ------------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------------

    def record_state(self):
        state = {
            'shapes': [s.to_dict() for s in self.shapes],
            'next_id': self.next_shape_id
        }
        self.undo_stack.append(state)
        if len(self.undo_stack) > self.max_undo:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self.app.file_manager.mark_modified()

    def undo(self):
        if not self.undo_stack:
            return
        current = {'shapes': [s.to_dict() for s in self.shapes], 'next_id': self.next_shape_id}
        self.redo_stack.append(current)
        self.restore_state(self.undo_stack.pop())
        self.app.status_bar.config(text="Undo")

    def redo(self):
        if not self.redo_stack:
            return
        current = {'shapes': [s.to_dict() for s in self.shapes], 'next_id': self.next_shape_id}
        self.undo_stack.append(current)
        self.restore_state(self.redo_stack.pop())
        self.app.status_bar.config(text="Redo")

    def restore_state(self, state):
        self.clear_all(record_undo=False)
        self.next_shape_id = state['next_id']
        for shape_data in state['shapes']:
            self.add_shape(Shape.from_dict(shape_data), record_undo=False)
        self.rebuild_connections()
        self.redraw_junctions()

    # ------------------------------------------------------------------
    # Orthogonal path computation
    # ------------------------------------------------------------------

    @staticmethod
    def ortho_path(points, routing="h_first"):
        """
        Convert a list of [x, y] points into a fully orthogonal path by
        inserting a bend point wherever two consecutive points are not
        axis-aligned.

        routing="h_first"  →  bend goes horizontal first, then vertical
        routing="v_first"  →  bend goes vertical first, then horizontal
        """
        if len(points) < 2:
            return [list(p) for p in points]

        result = [list(points[0])]
        for i in range(1, len(points)):
            prev = result[-1]
            curr = list(points[i])
            dx = abs(curr[0] - prev[0])
            dy = abs(curr[1] - prev[1])
            if dx > 0.5 and dy > 0.5:
                # Not axis-aligned — insert one bend point
                if routing == "v_first":
                    result.append([prev[0], curr[1]])
                else:  # h_first
                    result.append([curr[0], prev[1]])
            result.append(curr)
        return result

    # ==================================================================
    # ORTHOGONAL ROUTER — internals. See the module docstring for the
    # call-graph map and invariants before editing anything below.
    # ==================================================================

    def _hyst(self, key, value, band):
        """Hysteretic boolean: flip to True only once value rises above +band
        and to False only once it drops below -band; inside the band hold the
        previous decision. Stops a wire snapping back and forth at the
        crossover where a block passes level with its source.
        """
        prev = self._route_state.get(key)
        if value > band:
            state = True
        elif value < -band:
            state = False
        else:
            state = prev if prev is not None else (value >= 0)
        self._route_state[key] = state
        return state

    def _resolve_pin(self, target, wire, endpoint):
        """(side, port_name, (ax, ay)) of the pin this wire endpoint binds to.

        Resolve by the stored port_name; if that's missing (the wire snapped to
        the block edge, not a named pin), fall back to the nearest pin to the
        endpoint. Returns None when the target has no ports.
        """
        ports = getattr(target, 'ports', None) or []
        if not ports:
            return None
        conn = next((c for c in wire.connections
                     if c.get('endpoint') == endpoint
                     and c.get('target_id') == target.shape_id), None)
        pn = conn.get('port_name') if conn else None
        p = next((pp for pp in ports if pp['name'] == pn), None) if pn else None
        if p is None:
            ex, ey = (wire.x1, wire.y1) if endpoint == 'start' else (wire.x2, wire.y2)
            p = min(ports, key=lambda pp: (lambda a: (a[0] - ex) ** 2 + (a[1] - ey) ** 2)
                    (target.port_anchor(pp['name'])))
        return (p.get('side', 'L'), p['name'], target.port_anchor(p['name']))

    def _side_channel(self, target, side, wire_id, endpoint):
        """This wire-endpoint's rank among ALL wires bound to ``side`` of
        ``target``, the count, and a side-wide directional bias.

        Ranks by WIRE (unique per wire), not by pin — so two wires sharing a
        pin, or bound to the block edge, still get distinct channels and never
        overlap. Bias is the summed (source - pin) offset along the side axis;
        its sign sets the fan order once for the whole side.
        """
        lr = side in ('L', 'R')
        entries = []   # (pin_coord, wire_id, endpoint, delta)
        for s in self.shapes:
            if s.shape_type not in LINE_TYPES:
                continue
            for ep in ('start', 'end'):
                conn = next((c for c in s.connections
                             if c.get('endpoint') == ep
                             and c.get('target_id') == target.shape_id), None)
                if not conn:
                    continue
                res = self._resolve_pin(target, s, ep)
                if not res or res[0] != side:
                    continue
                ax, ay = res[2]
                wps = s.waypoints or []
                far = (wps[0] if wps else [s.x2, s.y2]) if ep == 'start' \
                    else (wps[-1] if wps else [s.x1, s.y1])
                delta = (far[1] - ay) if lr else (far[0] - ax)
                entries.append(((ay if lr else ax), s.shape_id, ep, delta))
        entries.sort(key=lambda e: (e[0], e[1], e[2]))
        m = len(entries)
        idx = next((i for i, e in enumerate(entries)
                    if e[1] == wire_id and e[2] == endpoint), 0)
        side_bias = sum(e[3] for e in entries)
        return idx, m, side_bias

    def _approach_point(self, line_shape, endpoint):
        """A staggered turn point just ahead of a connected pin.

        The turn distance grows with the pin's index on its side, so wires
        landing on stacked pins each bend at a distinct offset (fanned out)
        instead of stacking into one column at the block edge.
        Returns None when the endpoint is not bound to a pin.
        """
        conn = next((c for c in line_shape.connections
                     if c.get('endpoint') == endpoint
                     and c.get('target_id') is not None), None)
        if not conn:
            return None
        target = next((s for s in self.shapes
                       if s.shape_id == conn['target_id']), None)
        if target is None:
            return None
        # An off-page connector is a plain terminal — no staggered approach.
        # Only the block/mux end of the wire fans into channels; this removes
        # the duplicate corners and stub artifacts at the connector side.
        if target.shape_type in ('connector', 'connector_on'):
            return None
        res = self._resolve_pin(target, line_shape, endpoint)
        if res is None:
            return None
        side, port_name, (ex, ey) = res   # ex,ey = the pin anchor
        dx, dy = PORT_OUTWARD.get(side, (-1, 0))

        # Neighbouring point the wire heads toward (first/last waypoint, else
        # the far endpoint) — tells us which way the wire runs.
        wps = line_shape.waypoints or []
        if endpoint == 'start':
            rx, ry = (wps[0] if wps else [line_shape.x2, line_shape.y2])
        else:
            rx, ry = (wps[-1] if wps else [line_shape.x1, line_shape.y1])

        # Decision boundaries get a half-cell dead-band (hysteresis) so the
        # route doesn't flip back and forth right as the block passes level
        # with the wire's source.
        band = port_lead_length() * 0.5
        kbase = "%s:%s" % (line_shape.shape_id, endpoint)

        # Is the wire coming from the side the pin faces? (dot product of the
        # pin->source vector with the pin's outward direction.)
        proj = (rx - ex) * dx + (ry - ey) * dy
        outward = self._hyst(kbase + ":out", proj, band)

        # How many wires share this side, this wire's rank, and a single
        # side-wide fan direction (so the channels never collide/overlap).
        rank_idx, m, side_bias = self._side_channel(
            target, side, line_shape.shape_id, endpoint)
        side_positive = self._hyst("S:%s:%s" % (target.shape_id, side),
                                   side_bias, band)

        # Is the OTHER end of this wire also bound to a pin? The clean single
        # elbow reaches to the far point's raw coordinate, which is correct
        # only when that far end is a free source. When both ends are pins
        # (e.g. off-page connector -> mux input), that reach collides with the
        # other end's own approach and makes a weird zigzag — so fall through
        # to the perpendicular staggered form on both ends instead.
        other_ep = 'end' if endpoint == 'start' else 'start'
        other_pinned = self._end_has_pin_approach(line_shape, other_ep)

        if outward and m <= 1 and not other_pinned:
            # Lone wire from the side the pin faces: one clean elbow entering
            # the pin perpendicular, bend lined up to the pin (e.g. directly
            # above a top pin — horizontal from source, then a single 90 deg).
            corner = [rx, ey] if dx != 0 else [ex, ry]
            return [corner]

        # Otherwise fan into channels packed against the block, using the
        # side-wide direction so wires never cross, bend nearest the block.
        channel = (m - 1 - rank_idx) if side_positive else rank_idx
        dist = port_lead_length() * (channel + 1)
        tip = [ex + dx * dist, ey + dy * dist]
        if m <= 1:
            # Single wire on this side: a plain perpendicular exit is enough.
            # Adding the reaching corner here would collide with the other
            # end's approach on perpendicular pin pairs (e.g. block 'out' on the
            # right -> mux 'sel' on top) and make a little square loop. Let
            # ortho_path join the two tips with one clean bend instead.
            return [tip]
        corner = [tip[0], ry] if dx != 0 else [rx, tip[1]]
        return [corner, tip]

    def _wire_end_pinned(self, shape, ep):
        return any(c.get('endpoint') == ep and c.get('port_name')
                   for c in shape.connections)

    def _both_ends_pinned(self, shape):
        return (self._wire_end_pinned(shape, 'start')
                and self._wire_end_pinned(shape, 'end'))

    def _end_has_pin_approach(self, shape, ep):
        """True if this endpoint will get a staggered pin approach: it binds to
        a ported, non-connector shape. Mirrors _approach_point's own resolution
        (which falls back to the nearest pin), so it does NOT require an explicit
        port_name. Used so both ends of a pin-to-pin wire are treated the same.
        """
        conn = next((c for c in shape.connections
                     if c.get('endpoint') == ep
                     and c.get('target_id') is not None), None)
        if not conn:
            return False
        target = next((s for s in self.shapes
                       if s.shape_id == conn['target_id']), None)
        if target is None or target.shape_type in ('connector', 'connector_on'):
            return False
        return bool(getattr(target, 'ports', None))

    def _honor_waypoints(self, shape):
        """Whether to route this wire through its stored waypoints verbatim.

        Stored bends are honored as drawn so a freshly placed waypoint never
        jumps when the wire is finished. A SOFT manual route (drawn with
        click-bends) is later released to the auto-router the moment a connected
        component MOVES (see update_connected_lines), so it reroutes cleanly
        then — but not before. An explicit route (user_routed, from dragging or
        inserting a waypoint) is kept through moves.

        - user_routed: explicit per-wire override — always honored.
        - manual_route: soft manual from drawing — honored until a connected
          component moves.
        """
        if not shape.waypoints:
            return False
        if getattr(shape, 'user_routed', False):
            return True
        if getattr(shape, 'manual_route', False):
            return True
        return False

    def ortho_points(self, shape):
        """Full ortho point list including staggered pin approaches."""
        if self._honor_waypoints(shape):
            return ([[shape.x1, shape.y1]]
                    + [list(w) for w in (shape.waypoints or [])]
                    + [[shape.x2, shape.y2]])
        # Auto-routed: ignore any stale stored waypoints and rebuild the path
        # from the endpoints + perpendicular staggered approaches.
        pts = [[shape.x1, shape.y1], [shape.x2, shape.y2]]
        sa = self._approach_point(shape, 'start')
        if sa:
            pts[1:1] = list(reversed(sa))   # start: pin -> tip -> corner -> body
        ea = self._approach_point(shape, 'end')
        if ea:
            pts[-1:-1] = ea                 # end: body -> corner -> tip -> pin
        return pts

    # ------------------------------------------------------------------
    # Shape lifecycle
    # ------------------------------------------------------------------

    # ==================================================================
    # END ROUTER — rendering + document state below.
    # ==================================================================

    def add_shape(self, shape, record_undo=True):
        if shape.shape_id == 0:
            shape.shape_id = self.next_shape_id
            self.next_shape_id += 1
        self.draw_shape(shape)
        self.shapes.append(shape)
        if record_undo:
            self.redraw_junctions()
            self.record_state()

    def wire_arrow(self, shape):
        """Tk arrow constant for a wire, honoring an explicit arrow_ends
        override and falling back to the shape-type default."""
        mode = getattr(shape, 'arrow_ends', None)
        if mode == 'none':
            return tk.NONE
        if mode == 'one':
            return tk.LAST
        if mode == 'both':
            return tk.BOTH
        return tk.LAST if shape.shape_type in ("arrow", "ortho_arrow") else tk.NONE

    def draw_shape(self, shape):
        canvas = self.app.canvas

        # Buses render as a thicker line with a larger arrowhead.
        is_bus = getattr(shape, "bus", False)
        lw = shape.width + 3 if is_bus else shape.width
        arsh = (20, 24, 8) if is_bus else (16, 20, 6)
        dash = dash_tuple(shape)

        if shape.shape_type in ("line", "arrow"):
            shape.canvas_id = canvas.create_line(
                shape.x1, shape.y1, shape.x2, shape.y2,
                fill=shape.color, width=lw, dash=dash,
                arrow=self.wire_arrow(shape), arrowshape=arsh, tags="shape"
            )

        elif shape.shape_type in ("ortho_line", "ortho_arrow"):
            all_pts = self.ortho_points(shape)
            path = self.ortho_path(all_pts, shape.routing)
            # Drop consecutive duplicate points so a zero-length final segment
            # never hides the arrowhead (e.g. a straight wire off an output pin).
            dedup = [path[0]]
            for p in path[1:]:
                if abs(p[0] - dedup[-1][0]) > 0.01 or abs(p[1] - dedup[-1][1]) > 0.01:
                    dedup.append(p)
            if len(dedup) < 2:
                dedup.append(list(dedup[-1]))
            flat = [c for pt in dedup for c in pt]
            kw = dict(fill=shape.color, width=lw, dash=dash,
                      tags="shape", joinstyle=tk.MITER,
                      arrow=self.wire_arrow(shape), arrowshape=arsh)
            shape.canvas_id = canvas.create_line(*flat, **kw)

        elif shape.shape_type in ["rectangle", "square", "register", "adder"]:
            shape.canvas_id = canvas.create_rectangle(
                shape.x1, shape.y1, shape.x2, shape.y2,
                outline=shape.color, width=shape.width,
                fill=shape.fill_color or "", tags="shape"
            )
        elif shape.shape_type == "mux":
            x1, y1, x2, y2 = shape.x1, shape.y1, shape.x2, shape.y2
            inset = min(20, abs(y2 - y1) * 0.18)
            shape.canvas_id = canvas.create_polygon(
                x1, y1, x1, y2, x2, y2 - inset, x2, y1 + inset,
                outline=shape.color, width=shape.width,
                fill=shape.fill_color or "", tags="shape"
            )
        elif shape.shape_type in ["circle", "ellipse"]:
            shape.canvas_id = canvas.create_oval(
                shape.x1, shape.y1, shape.x2, shape.y2,
                outline=shape.color, width=shape.width,
                fill=shape.fill_color or "", tags="shape"
            )
        elif shape.shape_type == "triangle":
            cx = (shape.x1 + shape.x2) / 2
            shape.canvas_id = canvas.create_polygon(
                cx, shape.y1, shape.x1, shape.y2, shape.x2, shape.y2,
                outline=shape.color, fill=shape.fill_color or "",
                width=shape.width, tags="shape"
            )
        elif shape.shape_type == "connector":
            shape.canvas_id = canvas.create_oval(
                shape.x1, shape.y1, shape.x2, shape.y2,
                outline=shape.color, width=max(2, shape.width),
                fill=shape.fill_color or "white", tags="shape"
            )
            cx = (shape.x1 + shape.x2) / 2
            cy = (shape.y1 + shape.y2) / 2
            name = getattr(shape, "conn_name", None) or "?"
            canvas.create_text(cx, cy, text=name, font=("Arial", 11, "bold"),
                               fill=self.label_color_for(shape), anchor=tk.CENTER,
                               tags=("port", self.ports_tag(shape)))
        elif shape.shape_type == "connector_on":
            shape.canvas_id = canvas.create_oval(
                shape.x1, shape.y1, shape.x2, shape.y2,
                outline=shape.color, width=max(2, shape.width),
                fill=shape.fill_color or "white", tags="shape"
            )
            # Inner concentric ring distinguishes the on-page connector from
            # the single-ring off-page one.
            inset = 4
            canvas.create_oval(
                shape.x1 + inset, shape.y1 + inset,
                shape.x2 - inset, shape.y2 - inset,
                outline=shape.color, width=max(1, shape.width - 1),
                tags=("port", self.ports_tag(shape))
            )
            cx = (shape.x1 + shape.x2) / 2
            cy = (shape.y1 + shape.y2) / 2
            name = getattr(shape, "conn_name", None) or "?"
            canvas.create_text(cx, cy, text=name, font=("Arial", 10, "bold"),
                               fill=self.label_color_for(shape), anchor=tk.CENTER,
                               tags=("port", self.ports_tag(shape)))
        elif shape.shape_type == "text":
            font_weight = "bold" if shape.font_bold else "normal"
            font_slant = "italic" if shape.font_italic else "roman"
            font = (shape.font_family, shape.font_size, font_weight, font_slant)
            align = getattr(shape, "text_align", "left") or "left"
            anchor = {"left": tk.NW, "center": tk.N, "right": tk.NE}.get(align, tk.NW)
            justify = {"left": tk.LEFT, "center": tk.CENTER,
                       "right": tk.RIGHT}.get(align, tk.LEFT)
            shape.canvas_id = canvas.create_text(
                shape.x1, shape.y1,
                text=shape.text, font=font, fill=shape.color,
                anchor=anchor, justify=justify, tags="shape"
            )

        if shape.label and shape.shape_type != "text":
            cx = (shape.x1 + shape.x2) / 2
            cy = (shape.y1 + shape.y2) / 2
            shape.label_canvas_id = canvas.create_text(
                cx + shape.label_offset_x, cy + shape.label_offset_y,
                text=shape.label, font=("Arial", 10, "normal"),
                fill="black", anchor=tk.CENTER, tags="shape_label"
            )

        self.draw_ports(shape)
        self.draw_wire_deco(shape)

    def ports_tag(self, shape):
        return f"ports_{shape.shape_id}"

    def deco_tag(self, shape):
        return f"deco_{shape.shape_id}"

    def netlabel_tag(self, shape):
        return f"netlabel_{shape.shape_id}"

    def slicelabel_tag(self, shape):
        return f"slicelabel_{shape.shape_id}"

    # ------------------------------------------------------------------
    # Draggable wire decorations: bit-slice tap label, net label
    # ------------------------------------------------------------------

    def slice_tap_point(self, shape):
        """(cx, cy, ux, uy) — the tap glyph's center point on the wire and
        the unit direction of the wire's first segment. Returns None if the
        wire has fewer than 2 points."""
        poly = self.wire_polyline(shape)
        if len(poly) < 2:
            return None
        (x0, y0), (x1, y1) = poly[0], poly[1]
        seg = math.hypot(x1 - x0, y1 - y0) or 1.0
        ux, uy = (x1 - x0) / seg, (y1 - y0) / seg
        d = min(22, seg * 0.5)
        cx, cy = x0 + ux * d, y0 + uy * d
        return cx, cy, ux, uy

    def slice_label_offset(self, shape):
        """Effective (dx, dy) of the slice label relative to its tap point —
        either the user's saved override, or the app's current default
        distance, offset perpendicular to the wire's first segment."""
        dx = getattr(shape, 'slice_label_dx', None)
        dy = getattr(shape, 'slice_label_dy', None)
        if dx is not None and dy is not None:
            return dx, dy
        tap = self.slice_tap_point(shape)
        d = getattr(self.app, 'default_slice_label_distance', 12)
        if tap is None:
            return (0, -d)
        _, _, ux, uy = tap
        return (-uy * d, -d)

    @staticmethod
    def polyline_point_at(poly, t):
        """(x, y, horiz) at arc-length fraction t (0..1) along a polyline."""
        total = 0.0
        seglens = []
        for i in range(len(poly) - 1):
            L = math.hypot(poly[i + 1][0] - poly[i][0], poly[i + 1][1] - poly[i][1])
            seglens.append(L)
            total += L
        if total <= 0:
            x, y = poly[0]
            return x, y, True
        target = max(0.0, min(1.0, t)) * total
        run = 0.0
        for i, L in enumerate(seglens):
            if run + L >= target or i == len(seglens) - 1:
                f = (target - run) / L if L > 0 else 0.0
                ax, ay = poly[i]
                bx, by = poly[i + 1]
                horiz = abs(bx - ax) >= abs(by - ay)
                return ax + (bx - ax) * f, ay + (by - ay) * f, horiz
            run += L
        x, y = poly[-1]
        return x, y, True

    @staticmethod
    def project_to_polyline(poly, px, py):
        """Arc-length fraction t (0..1) of the point on the polyline nearest
        to (px, py)."""
        total = 0.0
        best_d2, best_t = None, 0.0
        run = 0.0
        for i in range(len(poly) - 1):
            ax, ay = poly[i]
            bx, by = poly[i + 1]
            vx, vy = bx - ax, by - ay
            L2 = vx * vx + vy * vy
            L = math.sqrt(L2)
            f = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / L2))
            qx, qy = ax + vx * f, ay + vy * f
            d2 = (px - qx) ** 2 + (py - qy) ** 2
            if best_d2 is None or d2 < best_d2:
                best_d2, best_t = d2, run + L * f
            run += L
            total += L
        return (best_t / total) if total > 0 else 0.0

    def net_label_base_point(self, shape):
        """(mx, my, horiz) — the net label's anchor on the wire. A dragged
        label stores an arc-length fraction (net_label_t) so it stays put
        when the auto-router rebuilds the wire; otherwise the anchor is the
        midpoint of the longest segment. Returns None if the wire has
        fewer than 2 points."""
        poly = self.wire_polyline(shape)
        if len(poly) < 2:
            return None
        t = getattr(shape, 'net_label_t', None)
        if t is not None:
            return self.polyline_point_at(poly, t)
        best, blen = (poly[0], poly[1]), -1.0
        for i in range(len(poly) - 1):
            a, b = poly[i], poly[i + 1]
            seglen = math.hypot(b[0] - a[0], b[1] - a[1])
            if seglen > blen:
                blen, best = seglen, (a, b)
        (ax, ay), (bx, by) = best
        mx, my = (ax + bx) / 2, (ay + by) / 2
        horiz = abs(bx - ax) >= abs(by - ay)
        return mx, my, horiz

    def net_label_offset(self, shape):
        """Effective (dx, dy) of the net label relative to its base point —
        either the user's saved override, or the app's current default
        distance applied above (horizontal wire) or beside (vertical wire)."""
        dx = getattr(shape, 'net_label_dx', None)
        dy = getattr(shape, 'net_label_dy', None)
        if dx is not None and dy is not None:
            return dx, dy
        base = self.net_label_base_point(shape)
        d = getattr(self.app, 'default_net_label_distance', 9)
        if base is None:
            return (0, -d)
        _, _, horiz = base
        return (0, -d) if horiz else (d, 0)

    def draw_wire_deco(self, shape):
        """Bit-slice tap glyph and net label on a wire — both draggable."""
        if shape.shape_type not in LINE_TYPES:
            return
        poly = self.wire_polyline(shape)
        if len(poly) < 2:
            return
        canvas = self.app.canvas
        tag = self.deco_tag(shape)

        label = getattr(shape, "slice_label", None)
        if label:
            tap = self.slice_tap_point(shape)
            if tap:
                cx, cy, ux, uy = tap
                canvas.create_line(cx - 7, cy + 7, cx + 7, cy - 7,
                                   fill=shape.color, width=max(1, shape.width),
                                   tags=("deco", tag))
                dx, dy = self.slice_label_offset(shape)
                canvas.create_text(cx + dx, cy + dy,
                                   text=label, font=("Arial", 9),
                                   fill=shape.color, anchor=tk.CENTER,
                                   tags=("deco", tag, "deco_label",
                                         self.slicelabel_tag(shape)))

        net = getattr(shape, "net_name", None)
        if net:
            base = self.net_label_base_point(shape)
            if base:
                mx, my, _ = base
                dx, dy = self.net_label_offset(shape)
                canvas.create_text(mx + dx, my + dy,
                                   text=net, font=("Arial", 9, "italic"),
                                   fill="#1f6fc2", anchor=tk.CENTER,
                                   tags=("deco", tag, "net_label",
                                         self.netlabel_tag(shape)))

    def label_color_for(self, shape):
        """Text color for interior pin names / glyphs that contrasts with
        the shape's fill, so labels stay readable on a dark fill."""
        fill = getattr(shape, "fill_color", None)
        # Connectors default to a white fill when none is set.
        if not fill and shape.shape_type in ("connector", "connector_on"):
            fill = "white"
        if not fill:
            return "#333333"
        try:
            r, g, b = self.app.canvas.winfo_rgb(fill)
        except Exception:
            return "#333333"
        lum = (0.299 * r + 0.587 * g + 0.114 * b) / 65535.0
        return "#333333" if lum >= 0.55 else "#f0f0f0"

    def draw_ports(self, shape):
        """Draw a pin stub + dot + name label for every named port."""
        if not getattr(shape, "ports", None):
            return
        canvas = self.app.canvas
        tag = self.ports_tag(shape)
        lbl_col = self.label_color_for(shape)
        for p in shape.ports:
            px, py = shape.port_anchor(p['name'])   # edge anchor (wire attaches here)
            side = p.get('side', 'L')
            # A clk pin draws a clock-edge triangle pointing into the shape;
            # push its name label past the triangle tip so the two don't overlap.
            off = 12 if p['name'].lower() == 'clk' else (4 if side in ('L', 'R') else 5)
            if side == 'L':
                lx, ly, anch = px + off, py, tk.W
            elif side == 'R':
                lx, ly, anch = px - off, py, tk.E
            elif side == 'T':
                lx, ly, anch = px, py + off, tk.N
            else:  # 'B'
                lx, ly, anch = px, py - off, tk.S
            canvas.create_oval(px - 2.5, py - 2.5, px + 2.5, py + 2.5,
                               fill=shape.color, outline=shape.color, tags=("port", tag))
            if not p.get('hide_label'):
                canvas.create_text(lx, ly, text=p['name'], font=("Arial", 8),
                                   fill=lbl_col, anchor=anch, tags=("port", tag, "port_label"))

            # Clock-edge triangle on a pin literally named 'clk'.
            if p['name'].lower() == 'clk':
                tri = 7
                if side == 'L':
                    pts = (px, py - tri, px, py + tri, px + tri + 2, py)
                elif side == 'R':
                    pts = (px, py - tri, px, py + tri, px - tri - 2, py)
                elif side == 'T':
                    pts = (px - tri, py, px + tri, py, px, py + tri + 2)
                else:
                    pts = (px - tri, py, px + tri, py, px, py - tri - 2)
                canvas.create_polygon(*pts, outline=shape.color, fill="",
                                      width=max(1, shape.width - 1), tags=("port", tag))

        self.draw_primitive_decor(shape, tag)

    def draw_primitive_decor(self, shape, tag):
        """Built-in glyphs that move/clear with the shape's port group."""
        canvas = self.app.canvas
        cx = (shape.x1 + shape.x2) / 2
        cy = (shape.y1 + shape.y2) / 2
        if shape.shape_type == "adder":
            canvas.create_text(cx, cy, text="+", font=("Arial", 18, "bold"),
                               fill=self.label_color_for(shape), anchor=tk.CENTER, tags=("port", tag))

    def flip_routing(self, shape):
        """Toggle h_first / v_first routing on an ortho line."""
        if shape.shape_type not in ("ortho_line", "ortho_arrow"):
            return
        shape.routing = "v_first" if shape.routing != "v_first" else "h_first"
        self.redraw_shape(shape)
        self.record_state()
        label = "vertical-first" if shape.routing == "v_first" else "horizontal-first"
        self.app.status_bar.config(text=f"Routing: {label}")

    def delete_shape(self, shape):
        if shape in self.shapes:
            self.record_state()
            self.app.canvas.delete(shape.canvas_id)
            self.app.canvas.delete(self.ports_tag(shape))
            self.app.canvas.delete(self.deco_tag(shape))
            if shape.label_canvas_id:
                self.app.canvas.delete(shape.label_canvas_id)
            for s in self.shapes:
                s.connections = [c for c in s.connections
                                 if c['target_id'] != shape.shape_id]
            self.shapes.remove(shape)
            self.clear_selection()
            self.redraw_junctions()

    def delete_shapes(self, shapes):
        """Delete several shapes as ONE undoable action (group delete)."""
        victims = [s for s in shapes if s in self.shapes]
        if not victims:
            return
        self.record_state()
        victim_ids = {s.shape_id for s in victims}
        for shape in victims:
            self.app.canvas.delete(shape.canvas_id)
            self.app.canvas.delete(self.ports_tag(shape))
            self.app.canvas.delete(self.deco_tag(shape))
            if shape.label_canvas_id:
                self.app.canvas.delete(shape.label_canvas_id)
        # Drop connections pointing at any deleted shape.
        for s in self.shapes:
            s.connections = [c for c in s.connections
                             if c.get('target_id') not in victim_ids]
        self.shapes = [s for s in self.shapes if s.shape_id not in victim_ids]
        self.clear_selection()
        self.redraw_junctions()

    def clear_all(self, record_undo=True):
        if record_undo and self.shapes:
            self.record_state()
        if hasattr(self.app, 'canvas'):
            self.app.canvas.delete("shape")
            self.app.canvas.delete("shape_label")
            self.app.canvas.delete("port")
            self.app.canvas.delete("deco")
            self.app.canvas.delete("junction")
        self.shapes.clear()
        self.clear_selection()
        self.next_shape_id = 1

    # ------------------------------------------------------------------
    # Sheets / drawing package
    # ------------------------------------------------------------------

    def commit_active(self):
        """Serialize the live sheet back into its record."""
        rec = self.sheets[self.active_sheet]
        rec['shapes'] = [s.to_dict() for s in self.shapes]
        rec['next_id'] = self.next_shape_id

    def _clear_canvas_items(self):
        canvas = self.app.canvas
        for tag in ("shape", "shape_label", "port", "deco", "junction",
                    "net_highlight", "highlight", "endpoint_handle",
                    "resize_handle", "label_highlight", "drc", "page"):
            canvas.delete(tag)

    def _load_active(self):
        """Repaint the canvas from the active sheet's stored shapes."""
        if not hasattr(self.app, 'canvas'):
            return
        self._clear_canvas_items()
        self.shapes = []
        rec = self.sheets[self.active_sheet]
        self.next_shape_id = rec.get('next_id', 1)
        for sd in rec.get('shapes', []):
            self.add_shape(Shape.from_dict(dict(sd)), record_undo=False)
        self.rebuild_connections()
        self.redraw_junctions()
        self.clear_selection()
        self.app.update_scrollregion()
        self.app.draw_page_boundary()
        self.app.draw_grid()
        self.draw_title_block()
        if hasattr(self.app, 'refresh_sheet_tabs'):
            self.app.refresh_sheet_tabs()

    def switch_sheet(self, index):
        if index == self.active_sheet or not (0 <= index < len(self.sheets)):
            return
        self.commit_active()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.active_sheet = index
        self._load_active()

    def add_sheet(self, name=None):
        self.commit_active()
        name = name or f"Sheet {len(self.sheets) + 1}"
        cur = self.sheets[self.active_sheet]
        self.sheets.append({'name': name, 'shapes': [], 'next_id': 1,
                            'width': cur.get('width', 1700),
                            'height': cur.get('height', 1100)})
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.active_sheet = len(self.sheets) - 1
        self._load_active()
        self.app.file_manager.mark_modified()

    def delete_sheet(self, index):
        if len(self.sheets) <= 1 or not (0 <= index < len(self.sheets)):
            return False
        if index != self.active_sheet:
            self.commit_active()
        del self.sheets[index]
        if self.active_sheet > index:
            self.active_sheet -= 1
        elif self.active_sheet == index:
            self.active_sheet = min(index, len(self.sheets) - 1)
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._load_active()
        self.app.file_manager.mark_modified()
        return True

    def rename_sheet(self, index, name):
        if 0 <= index < len(self.sheets) and name:
            self.sheets[index]['name'] = name
            if index == self.active_sheet:
                self.draw_title_block()
            if hasattr(self.app, 'refresh_sheet_tabs'):
                self.app.refresh_sheet_tabs()
            self.app.file_manager.mark_modified()

    def move_sheet(self, index, new_index):
        """Reorder a sheet within the package. The SAME sheet stays active
        (its index follows the move); undo history is preserved since no
        sheet content changes."""
        n = len(self.sheets)
        if not (0 <= index < n) or not (0 <= new_index < n) or index == new_index:
            return False
        # The active sheet lives in self.shapes; keep its record in sync first.
        self.commit_active()
        sheet = self.sheets.pop(index)
        self.sheets.insert(new_index, sheet)
        a = self.active_sheet
        if a == index:
            a = new_index
        elif index < a <= new_index:
            a -= 1
        elif new_index <= a < index:
            a += 1
        self.active_sheet = a
        self.draw_title_block()
        if hasattr(self.app, 'refresh_sheet_tabs'):
            self.app.refresh_sheet_tabs()
        self.app.file_manager.mark_modified()
        return True

    def set_sheet_size(self, index, width, height):
        """Set page width/height (in canvas pixels) for one sheet."""
        if not (0 <= index < len(self.sheets)):
            return
        width = max(200, int(width))
        height = max(200, int(height))
        self.sheets[index]['width'] = width
        self.sheets[index]['height'] = height
        if index == self.active_sheet and hasattr(self.app, 'canvas'):
            self.app.update_scrollregion()
            self.app.draw_page_boundary()
            self.app.draw_grid()
            self.draw_title_block()
        self.app.file_manager.mark_modified()

    def serialize_package(self):
        self.commit_active()
        return {
            'version': '2.0',
            'package_title': self.package_title,
            'active': self.active_sheet,
            'sheets': [dict(name=s['name'], shapes=s['shapes'],
                            next_id=s.get('next_id', 1),
                            width=s.get('width', 1700),
                            height=s.get('height', 1100)) for s in self.sheets],
        }

    def load_package(self, data):
        """Load either a v2 multi-sheet package or a legacy single-sheet file."""
        if 'sheets' in data:
            self.package_title = data.get('package_title', 'Untitled')
            self.sheets = [{'name': s.get('name', f'Sheet {i + 1}'),
                            'shapes': s.get('shapes', []),
                            'next_id': s.get('next_id', 1),
                            'width': s.get('width', 1700),
                            'height': s.get('height', 1100)}
                           for i, s in enumerate(data['sheets'])] or \
                           [{'name': 'Sheet 1', 'shapes': [], 'next_id': 1,
                             'width': 1700, 'height': 1100}]
            self.active_sheet = min(data.get('active', 0), len(self.sheets) - 1)
        else:
            # Legacy: wrap the flat shape list into a single sheet.
            self.package_title = 'Untitled'
            self.sheets = [{'name': 'Sheet 1',
                            'shapes': data.get('shapes', []),
                            'next_id': 1, 'width': 1700, 'height': 1100}]
            self.active_sheet = 0
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._load_active()

    def reset_package(self):
        self.clear_all(record_undo=False)
        self.package_title = 'Untitled'
        self.sheets = [{'name': 'Sheet 1', 'shapes': [], 'next_id': 1,
                        'width': 1700, 'height': 1100}]
        self.active_sheet = 0
        self._load_active()

    def draw_title_block(self):
        """Draw the per-sheet title block (name, page N of M, date) bottom-right.

        Anchored to the SHEET's own page size, not the canvas viewport, so it
        sits at the actual page corner regardless of window size or scroll
        position.
        """
        if not hasattr(self.app, 'canvas'):
            return
        canvas = self.app.canvas
        canvas.delete("titleblock")
        sheet = self.sheets[self.active_sheet]
        w = sheet.get('width', 1700)
        h = sheet.get('height', 1100)
        bw, bh = 330, 92
        x2, y2 = w - 8, h - 8
        x1, y1 = x2 - bw, y2 - bh
        r1, r2 = y1 + bh * 0.40, y1 + bh * 0.70
        pad = 8
        canvas.create_rectangle(x1, y1, x2, y2, fill="white", outline="black",
                                width=1.5, tags=("titleblock",))
        canvas.create_line(x1, r1, x2, r1, fill="black", tags=("titleblock",))
        canvas.create_line(x1, r2, x2, r2, fill="black", tags=("titleblock",))
        canvas.create_text(x1 + pad, y1 + pad, anchor=tk.NW, font=("Arial", 11, "bold"),
                           text=self.package_title, tags=("titleblock",))
        canvas.create_text(x2 - pad, y1 + pad, anchor=tk.NE, font=("Arial", 9),
                           text="abDraw", tags=("titleblock",))
        canvas.create_text(x1 + pad, r1 + 5, anchor=tk.NW, font=("Arial", 9),
                           text=sheet['name'], tags=("titleblock",))
        canvas.create_text(x2 - pad, r1 + 5, anchor=tk.NE, font=("Arial", 9),
                           text=f"Sheet {self.active_sheet + 1} of {len(self.sheets)}",
                           tags=("titleblock",))
        canvas.create_text(x1 + pad, r2 + 4, anchor=tk.NW, font=("Arial", 8),
                           fill="#555555", text=datetime.date.today().isoformat(),
                           tags=("titleblock",))
        canvas.tag_raise("titleblock")

    # ------------------------------------------------------------------
    # Netlist & validation (Phase 6)
    # ------------------------------------------------------------------

    def _sheet_shapes(self):
        """(index, name, [Shape]) for every sheet; active sheet uses live objects."""
        self.commit_active()
        out = []
        for i, rec in enumerate(self.sheets):
            if i == self.active_sheet:
                shapes = list(self.shapes)
            else:
                shapes = [Shape.from_dict(dict(sd)) for sd in rec.get('shapes', [])]
            out.append((i, rec['name'], shapes))
        return out

    @staticmethod
    def _block_label(s):
        if getattr(s, 'conn_name', None):
            return s.conn_name
        if getattr(s, 'label', None):
            return s.label
        return f"{s.shape_type}{s.shape_id}"

    def build_netlist(self):
        """Trace electrical connectivity across all sheets.

        Merge rules: explicit pin connections, coincident wire endpoints
        (junctions), endpoint-on-segment T-junctions, shared net labels
        (cross-sheet), and off-page connectors sharing a name (cross-sheet).
        Returns {'nets': [...], 'unconnected': [...], 'dangling': [...]}.
        """
        parent = {}

        def node(k):
            parent.setdefault(k, k)
            return k

        def find(x):
            node(x)
            root = x
            while parent[root] != root:
                root = parent[root]
            while parent[x] != root:
                parent[x], x = root, parent[x]
            return root

        def union(a, b):
            ra, rb = find(node(a)), find(node(b))
            if ra != rb:
                parent[rb] = ra

        pin_nodes = {}      # node key -> (sheet_name, block_label, port)
        referenced = set()  # pin nodes a wire actually lands on

        for si, sname, shapes in self._sheet_shapes():
            blocks = [s for s in shapes if s.shape_type not in LINE_TYPES]
            wires = [s for s in shapes if s.shape_type in LINE_TYPES
                     and not getattr(s, 'annotation', False)]

            for b in blocks:
                for p in (getattr(b, 'ports', None) or []):
                    pk = f"P:{si}:{b.shape_id}:{p['name']}"
                    node(pk)
                    pin_nodes[pk] = (sname, self._block_label(b), p['name'])
                if b.shape_type == 'connector' and getattr(b, 'conn_name', None):
                    union(f"P:{si}:{b.shape_id}:io", f"K:{b.conn_name}")
                if b.shape_type == 'connector_on' and getattr(b, 'conn_name', None):
                    # On-page connector: scope the net key to THIS sheet only.
                    union(f"P:{si}:{b.shape_id}:io", f"K:{si}:{b.conn_name}")

            raw = {}
            for w in wires:
                def endnode(ep):
                    conn = next((c for c in w.connections
                                 if c.get('endpoint') == ep), None)
                    if conn and conn.get('port_name') and conn.get('target_id') is not None:
                        pk = f"P:{si}:{conn['target_id']}:{conn['port_name']}"
                        referenced.add(node(pk))
                        return pk
                    x, y = (w.x1, w.y1) if ep == 'start' else (w.x2, w.y2)
                    return f"C:{si}:{round(x / 2) * 2}:{round(y / 2) * 2}"
                ns, ne = endnode('start'), endnode('end')
                union(ns, ne)
                if getattr(w, 'net_name', None):
                    union(ns, f"L:{w.net_name}")
                    union(ne, f"L:{w.net_name}")
                pts = [[w.x1, w.y1]] + [list(p) for p in (w.waypoints or [])] + [[w.x2, w.y2]]
                raw[w.shape_id] = (pts, ns, ne)

            items = list(raw.items())
            for wid, (pts, ns, ne) in items:
                for ep_pt, ep_node in ((pts[0], ns), (pts[-1], ne)):
                    for wid2, (pts2, ns2, ne2) in items:
                        if wid2 == wid:
                            continue
                        if any(self._seg_has_interior_point(ep_pt, pts2[k], pts2[k + 1])
                               for k in range(len(pts2) - 1)):
                            union(ep_node, ns2)
                            break

        comps = {}
        for k in list(parent.keys()):
            comps.setdefault(find(k), []).append(k)

        nets, auto = [], 0
        for members in comps.values():
            pins = sorted(set(pin_nodes[m] for m in members if m in pin_nodes))
            if not pins:
                continue
            lbl = next((m[2:] for m in members if m.startswith('L:')), None)
            cn = next((m[2:] for m in members if m.startswith('K:')), None)
            has_wire = any(m[:2] in ('C:', 'L:', 'K:') for m in members) or len(pins) > 1
            name = lbl or cn
            if not name:
                if not has_wire:
                    continue
                auto += 1
                name = "N$%d" % auto
            nets.append({'name': name, 'pins': pins})

        nets.sort(key=lambda n: n['name'])
        unconnected = sorted(v for k, v in pin_nodes.items() if k not in referenced)
        dangling = [n['name'] for n in nets if len(n['pins']) == 1]
        return {'nets': nets, 'unconnected': unconnected, 'dangling': dangling}

    def mark_unconnected_pins(self):
        """Draw red DRC rings around unconnected pins on the ACTIVE sheet."""
        if not hasattr(self.app, 'canvas'):
            return 0
        canvas = self.app.canvas
        canvas.delete("drc")
        report = self.build_netlist()
        active_name = self.sheets[self.active_sheet]['name']
        bad = {(b, p) for (sn, b, p) in report['unconnected'] if sn == active_name}
        count = 0
        for s in self.shapes:
            if s.shape_type in LINE_TYPES:
                continue
            for pdef in (getattr(s, 'ports', None) or []):
                if (self._block_label(s), pdef['name']) in bad:
                    ax, ay = s.port_anchor(pdef['name'])
                    canvas.create_oval(ax - 6, ay - 6, ax + 6, ay + 6,
                                       outline="#d62828", width=2, tags=("drc",))
                    count += 1
        canvas.tag_raise("drc")
        return count

    def clear_selection(self):
        self.selected_shape = None
        self.selected_shapes = []
        self.editing_endpoint = None
        if hasattr(self.app, 'canvas'):
            self.app.canvas.delete("highlight")
            self.app.canvas.delete("endpoint_handle")
            self.app.canvas.delete("label_highlight")
            self.app.canvas.delete("resize_handle")
            self.app.canvas.delete("net_highlight")
            self.app.canvas.delete("group_highlight")
        self.app.editing_label = False
        self.app.label_shape = None
        self.app.resizing_shape = False
        self.app.resize_handle = None
        if hasattr(self.app, 'editing_waypoint'):
            self.app.editing_waypoint = None
        if hasattr(self.app, 'editing_segment'):
            self.app.editing_segment = None
        if hasattr(self.app, 'editing_net_label'):
            self.app.editing_net_label = None
        if hasattr(self.app, 'editing_slice_label'):
            self.app.editing_slice_label = None

    def clear_group_selection(self):
        """Drop the marquee group selection and its highlight."""
        self.selected_shapes = []
        if hasattr(self.app, 'canvas'):
            self.app.canvas.delete("group_highlight")

    def set_group_selection(self, shapes):
        """Make `shapes` the active group selection. Clears any single
        selection so the two selection modes never overlap visually."""
        self.selected_shape = None
        if hasattr(self.app, 'canvas'):
            for tag in ("highlight", "endpoint_handle", "resize_handle",
                        "net_highlight", "label_highlight"):
                self.app.canvas.delete(tag)
        self.selected_shapes = list(shapes)
        self.draw_group_highlight()

    def draw_group_highlight(self):
        """Dashed green box around every shape in the group selection."""
        canvas = self.app.canvas
        canvas.delete("group_highlight")
        for shape in self.selected_shapes:
            b = self.app._shape_bounds(shape)
            if not b:
                continue
            canvas.create_rectangle(b[0] - 3, b[1] - 3, b[2] + 3, b[3] + 3,
                                    outline="#2e8b57", dash=(4, 3), width=2,
                                    tags="group_highlight")

    # Fixed offset applied to a pasted group so it doesn't land exactly on
    # top of the source (small, consistent — matches most drawing tools).
    PASTE_OFFSET = 20

    def copy_shape(self):
        """Copy the current selection (single OR marquee group) to the
        clipboard as plain dicts. Same-sheet AND cross-sheet paste both read
        this — the clipboard is app-level, not per-sheet."""
        shapes_to_copy = self.selected_shapes if self.selected_shapes else (
            [self.selected_shape] if self.selected_shape else [])
        if not shapes_to_copy:
            return
        self.clipboard = [s.to_dict() for s in shapes_to_copy]
        self.paste_count = 0
        n = len(shapes_to_copy)
        self.app.status_bar.config(
            text="Copied 1 shape" if n == 1 else f"Copied {n} shapes")

    def paste_shape(self, in_place=False):
        """Paste the clipboard onto the ACTIVE sheet (may differ from the
        sheet it was copied from), as one undo step.

        Repeated Ctrl+V cascades the offset (PASTE_OFFSET, 2x, 3x, ...) like
        most drawing tools, so successive pastes step diagonally instead of
        stacking exactly on each other. in_place=True (Paste in Place) skips
        the offset entirely and drops the copy exactly on the source
        position; it does NOT advance the cascade.

        Wire connections between two shapes that were copied TOGETHER are
        rewired to the new copies. A wire pinned to a block that was NOT
        copied (its target isn't in the clipboard set) is detached — it
        becomes a floating endpoint at the same relative position, since
        that target block may not even exist on the destination sheet.

        net_name / conn_name are kept as-is on copies, so a pasted wire or
        connector still joins the same net/node unless renamed afterward.
        """
        if not self.clipboard:
            return
        self.record_state()
        if in_place:
            off = 0
        else:
            self.paste_count += 1
            off = self.PASTE_OFFSET * self.paste_count
        id_map = {}
        new_dicts = []
        for src in self.clipboard:
            data = _copy.deepcopy(src)
            old_id = data.get('shape_id', 0)
            new_id = self.next_shape_id
            self.next_shape_id += 1
            id_map[old_id] = new_id
            data['shape_id'] = new_id
            data['canvas_id'] = None
            data['label_canvas_id'] = None
            data['x1'] = data.get('x1', 0) + off
            data['y1'] = data.get('y1', 0) + off
            data['x2'] = data.get('x2', 0) + off
            data['y2'] = data.get('y2', 0) + off
            data['waypoints'] = [[wp[0] + off, wp[1] + off]
                                  for wp in data.get('waypoints', [])]
            new_dicts.append(data)
        for data in new_dicts:
            kept = []
            for c in data.get('connections', []):
                tid = c.get('target_id')
                if tid in id_map:
                    nc = dict(c)
                    nc['target_id'] = id_map[tid]
                    kept.append(nc)
                # else: target wasn't part of the copied set — detach.
            data['connections'] = kept
        new_shapes = [Shape.from_dict(d) for d in new_dicts]
        for shape in new_shapes:
            self.draw_shape(shape)
            self.shapes.append(shape)
        self.redraw_junctions()
        self.set_group_selection(new_shapes)
        n = len(new_shapes)
        self.app.status_bar.config(
            text="Pasted 1 shape" if n == 1 else f"Pasted {n} shapes")

    def bring_to_front(self):
        if self.selected_shape:
            self.app.canvas.tag_raise(self.selected_shape.canvas_id)
            if getattr(self.selected_shape, 'label_canvas_id', None):
                self.app.canvas.tag_raise(self.selected_shape.label_canvas_id)
            # A connector's name text (and, for on-page, its inner ring) are
            # drawn as separate canvas items tagged with ports_tag(shape),
            # not stored on the shape itself — raise/lower that whole group
            # too so the WHOLE symbol (not just the outer circle) restacks.
            self.app.canvas.tag_raise(self.ports_tag(self.selected_shape))
            # Canvas stacking alone doesn't survive save/load or sheet switch
            # (those redraw shapes in self.shapes list order) — keep the list
            # order consistent with the visual stacking so it persists.
            if self.selected_shape in self.shapes:
                self.shapes.remove(self.selected_shape)
                self.shapes.append(self.selected_shape)
            self.app.status_bar.config(text="Brought to front")

    def send_to_back(self):
        if self.selected_shape:
            # Lower only to just above the "grid"/"page" background tags, not
            # to the absolute bottom of the canvas stack — an unqualified
            # tag_lower() drops the shape BELOW the opaque white page
            # rectangle, making it disappear instead of merely going behind
            # other shapes.
            self.app.canvas.tag_lower(self.selected_shape.canvas_id, "grid")
            if getattr(self.selected_shape, 'label_canvas_id', None):
                self.app.canvas.tag_lower(self.selected_shape.label_canvas_id, "grid")
            self.app.canvas.tag_lower(self.ports_tag(self.selected_shape), "grid")
            if self.selected_shape in self.shapes:
                self.shapes.remove(self.selected_shape)
                self.shapes.insert(0, self.selected_shape)
            self.app.status_bar.config(text="Sent to back")

    # ------------------------------------------------------------------
    # Connections & snapping
    # ------------------------------------------------------------------

    def rebuild_connections(self):
        for shape in self.shapes:
            if shape.shape_type in LINE_TYPES:
                for conn_data in shape.connections:
                    target = next((s for s in self.shapes
                                   if s.shape_id == conn_data['target_id']), None)
                    if target:
                        snap_x, snap_y = self.get_connection_point(target, shape, conn_data['endpoint'])
                        if conn_data['endpoint'] == 'start':
                            shape.x1, shape.y1 = snap_x, snap_y
                        else:
                            shape.x2, shape.y2 = snap_x, snap_y
                        self.redraw_shape(shape)

    def get_connection_point(self, target_shape, line_shape, endpoint):
        # Prefer a stored named-port binding so the wire stays pinned to the
        # exact pin (not merely the nearest edge point) when the block moves.
        conn = next((c for c in line_shape.connections
                     if c.get('endpoint') == endpoint
                     and c.get('target_id') == target_shape.shape_id), None)
        if conn and conn.get('port_name'):
            names = {p.get('name') for p in getattr(target_shape, 'ports', [])}
            if conn['port_name'] in names:
                return target_shape.port_anchor(conn['port_name'])
        x, y = (line_shape.x1, line_shape.y1) if endpoint == "start" else (line_shape.x2, line_shape.y2)
        snap_x, snap_y, _ = self.get_snap_point(x, y, line_shape)
        return snap_x, snap_y

    def _grid_snap_1d(self, v):
        """Round one coordinate to the active drawing grid, matching how
        block bounds already snap on move/resize (so a computed midpoint
        lands on the same dots as everything else). No-op if snapping is
        off or the grid spacing is unavailable/zero."""
        spacing = getattr(self.app, 'grid_spacing', 0) if getattr(self.app, 'snap_to_grid', False) else 0
        if not spacing:
            return v
        return round(v / spacing) * spacing

    def get_snap_point(self, x, y, exclude_shape=None, max_dist=None):
        min_dist = max_dist if max_dist is not None else self.snap_distance
        snap_x, snap_y = x, y
        snap_shape = None
        snap_port = None

        for shape in self.shapes:
            if shape == exclude_shape or shape.shape_type in LINE_TYPES:
                continue

            # Candidates are (px, py, port_name). Named ports carry their name;
            # generic geometric snap points use port_name=None.
            candidates = []
            for p in getattr(shape, "ports", []):
                ax, ay = shape.port_anchor(p['name'])
                candidates.append((ax, ay, p['name']))

            # Edge MIDPOINTS aren't guaranteed to fall on a grid line (a
            # box's width/height need not be an even multiple of the grid),
            # so a wire snapping to one can land strictly between dots.
            # Corners are already grid-aligned (shapes snap on move/resize),
            # so only midpoint-derived coordinates need re-snapping here.
            gx = self._grid_snap_1d

            if shape.shape_type in ["rectangle", "square", "register", "adder"]:
                mx, my = gx((shape.x1 + shape.x2) / 2), gx((shape.y1 + shape.y2) / 2)
                pts = [
                    (shape.x1, shape.y1), (shape.x2, shape.y1),
                    (shape.x1, shape.y2), (shape.x2, shape.y2),
                    (mx, shape.y1), (mx, shape.y2),
                    (shape.x1, my), (shape.x2, my),
                ]
                candidates.extend((px, py, None) for px, py in pts)
            elif shape.shape_type in ["circle", "ellipse"]:
                cx = gx((shape.x1 + shape.x2) / 2)
                cy = gx((shape.y1 + shape.y2) / 2)
                rx = abs(shape.x2 - shape.x1) / 2
                ry = abs(shape.y2 - shape.y1) / 2
                candidates.extend([
                    (cx - rx, cy, None), (cx + rx, cy, None),
                    (cx, cy - ry, None), (cx, cy + ry, None),
                ])
            elif shape.shape_type == "triangle":
                cx = gx((shape.x1 + shape.x2) / 2)
                candidates.extend([
                    (cx, shape.y1, None),
                    (shape.x1, shape.y2, None),
                    (shape.x2, shape.y2, None),
                ])

            for px, py, pname in candidates:
                dist = math.sqrt((x - px) ** 2 + (y - py) ** 2)
                # Give named ports a small priority bonus so they win over a
                # nearby generic edge point.
                eff = dist - (3 if pname else 0)
                if eff < min_dist:
                    min_dist = eff
                    snap_x, snap_y = px, py
                    snap_shape = shape
                    snap_port = pname

        self.last_snap_port = snap_port
        return snap_x, snap_y, snap_shape

    def redraw_shape(self, shape):
        self.app.canvas.delete(shape.canvas_id)
        self.app.canvas.delete(self.ports_tag(shape))
        self.app.canvas.delete(self.deco_tag(shape))
        if shape.label_canvas_id:
            self.app.canvas.delete(shape.label_canvas_id)
            shape.label_canvas_id = None
        self.draw_shape(shape)

    def wire_polyline(self, shape):
        """Drawn point list for a wire (straight or ortho), deduplicated."""
        if shape.shape_type in ("line", "arrow"):
            return [[shape.x1, shape.y1], [shape.x2, shape.y2]]
        if shape.shape_type in ("ortho_line", "ortho_arrow"):
            path = self.ortho_path(self.ortho_points(shape), shape.routing)
            dedup = [path[0]]
            for p in path[1:]:
                if abs(p[0] - dedup[-1][0]) > 0.01 or abs(p[1] - dedup[-1][1]) > 0.01:
                    dedup.append(list(p))
            return dedup
        return []

    @staticmethod
    def _seg_has_interior_point(pt, a, b, tol=2.5):
        """True if pt lies on segment a-b but not at either vertex."""
        px, py = pt
        ax, ay = a
        bx, by = b
        seglen = math.hypot(bx - ax, by - ay)
        if seglen == 0:
            return False
        cross = abs((bx - ax) * (py - ay) - (by - ay) * (px - ax)) / seglen
        if cross > tol:
            return False
        dot = (px - ax) * (bx - ax) + (py - ay) * (by - ay)
        if dot < 0 or dot > seglen * seglen:
            return False
        if math.hypot(px - ax, py - ay) <= tol or math.hypot(px - bx, py - by) <= tol:
            return False
        return True

    def redraw_junctions(self):
        """Draw a connection dot wherever 3+ conductors meet: either 3+ wire
        endpoints coincide, or one wire's endpoint lands on another wire's
        interior segment (a T-junction)."""
        if not hasattr(self.app, 'canvas'):
            return
        canvas = self.app.canvas
        canvas.delete("junction")
        for pt in self.compute_junctions():
            r = 4
            canvas.create_oval(pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r,
                               fill='black', outline='black', tags=("junction",))

    def compute_junctions(self, shapes=None):
        """Junction-dot points for the given shapes (defaults to self.shapes):
        wherever 3+ wire endpoints coincide, or an endpoint lands on another
        wire's interior segment (a T-junction)."""
        if shapes is None:
            shapes = self.shapes
        wires = [s for s in shapes if s.shape_type in LINE_TYPES
                 and not getattr(s, 'annotation', False)]
        polys = {s.shape_id: self.wire_polyline(s) for s in wires}

        def key(pt):
            return (round(pt[0] / 2.0) * 2, round(pt[1] / 2.0) * 2)

        terminals = []          # (shape_id, point)
        counts = {}
        for s in wires:
            poly = polys[s.shape_id]
            if len(poly) < 2:
                continue
            for pt in (poly[0], poly[-1]):
                terminals.append((s.shape_id, pt))
                counts[key(pt)] = counts.get(key(pt), 0) + 1

        dots = {}
        for sid, pt in terminals:
            if counts[key(pt)] >= 3:
                dots[key(pt)] = pt
        for sid, pt in terminals:
            for s2 in wires:
                if s2.shape_id == sid:
                    continue
                poly2 = polys[s2.shape_id]
                # A T-tap either lands mid-segment (interior point) OR exactly
                # on one of s2's own BEND vertices (a corner) — the latter is
                # excluded from _seg_has_interior_point on purpose (so a
                # wire's own bends never self-flag), but here s2 is a
                # DIFFERENT wire, so landing on its corner is a real junction.
                on_bend = any(key(poly2[j]) == key(pt) for j in range(1, len(poly2) - 1))
                if on_bend or any(self._seg_has_interior_point(pt, poly2[i], poly2[i + 1])
                                   for i in range(len(poly2) - 1)):
                    dots[key(pt)] = pt
                    break
        return list(dots.values())

    def shapes_for_sheet(self, index):
        """Live Shape objects for a sheet: the active sheet's live list, or a
        fresh deserialization for any other sheet. Used by the exporter, which
        temporarily points self.shapes at the result so the routing/junction
        geometry computes against the correct sheet."""
        if index == self.active_sheet:
            return self.shapes
        rec = self.sheets[index]
        return [Shape.from_dict(dict(sd)) for sd in rec.get('shapes', [])]

    def highlight_net_group(self, shape):
        """Halo every wire sharing the selected wire's net name, or every
        off-page connector sharing the selected connector's name. Returns the
        match count (including the selection itself)."""
        if not hasattr(self.app, 'canvas'):
            return 0
        canvas = self.app.canvas
        canvas.delete("net_highlight")
        net = getattr(shape, 'net_name', None)
        conn = getattr(shape, 'conn_name', None)
        if shape.shape_type in LINE_TYPES and net:
            matches = [s for s in self.shapes
                       if s.shape_type in LINE_TYPES and getattr(s, 'net_name', None) == net]
        elif shape.shape_type in ('connector', 'connector_on') and conn:
            matches = [s for s in self.shapes
                       if s.shape_type == shape.shape_type
                       and getattr(s, 'conn_name', None) == conn]
        else:
            return 0
        for s in matches:
            if s.shape_type in LINE_TYPES:
                flat = [c for pt in self.wire_polyline(s) for c in pt]
                if len(flat) >= 4:
                    canvas.create_line(*flat, fill="#9ecbff", width=s.width + 6,
                                       capstyle=tk.ROUND, joinstyle=tk.ROUND,
                                       tags="net_highlight")
            else:
                r = 6
                canvas.create_oval(s.x1 - r, s.y1 - r, s.x2 + r, s.y2 + r,
                                   outline="#3a86ff", width=3, tags="net_highlight")
        canvas.tag_lower("net_highlight")
        return len(matches)

    def update_connected_lines(self, moved_shape, skip_ids=None):
        """Re-pin wires connected to moved_shape's ports (and, for the
        auto-router, reroute them from scratch).

        skip_ids: wire shape_ids to leave untouched entirely — used for a
        group move, where those wires are themselves group members already
        translated as a rigid unit in _translate_group. Rerouting them here
        would discard that correct, already-consistent geometry and let the
        auto-router restagger multiple wires on the same pin side from
        scratch, which can come out differently than the original layout."""
        skip_ids = skip_ids or set()
        for shape in self.shapes:
            if shape.shape_id in skip_ids:
                continue
            if shape.shape_type not in LINE_TYPES:
                continue
            touched = False
            for conn in shape.connections:
                if isinstance(conn, dict) and conn.get('target_id') == moved_shape.shape_id:
                    snap_x, snap_y = self.get_connection_point(
                        moved_shape, shape, conn['endpoint'])
                    if conn['endpoint'] == 'start':
                        shape.x1, shape.y1 = snap_x, snap_y
                    else:
                        shape.x2, shape.y2 = snap_x, snap_y
                    touched = True
            if touched:
                # A SOFT manual route (drawn with click-bends) is released to
                # the auto-router now that a connected component moved, so it
                # reroutes cleanly with fresh perpendicular pin approaches. An
                # explicitly routed wire (user_routed) keeps its waypoints.
                if (shape.shape_type in ("ortho_line", "ortho_arrow")
                        and not getattr(shape, 'user_routed', False)):
                    shape.waypoints = []
                    shape.manual_route = False
                self.redraw_shape(shape)
        self.redraw_junctions()
