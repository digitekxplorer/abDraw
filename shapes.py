# ============================================================================
# FILE: shapes.py
# ============================================================================
"""
Shape data structures and utilities for abDraw
"""
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
import json
import math


@dataclass
class Connection:
    """Represents a connection between a line endpoint and a shape"""
    target_id: int  # ID of the target shape
    endpoint: str  # 'start' or 'end'

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)


# Grid spacing used to align port anchors. 0 = no snapping.
# The application sets this via set_port_grid() so pins land on the same
# grid the wires snap to.
_PORT_GRID = 0


def set_port_grid(spacing):
    global _PORT_GRID
    _PORT_GRID = spacing or 0


# Outward unit direction for each side, and the length of a pin's lead stub.
# Wires attach to the tip of this lead (offset from the block edge) so the
# orthogonal turn happens in open space, not against the block edge.
PORT_OUTWARD = {'L': (-1, 0), 'R': (1, 0), 'T': (0, -1), 'B': (0, 1)}


def port_lead_length():
    return _PORT_GRID if _PORT_GRID > 0 else 20


def edge_positions(start, end, count):
    """``count`` anchor coordinates between ``start`` and ``end``.

    Positions are evenly distributed, then (when a port grid is active)
    snapped to the grid while kept strictly increasing so two pins never
    collapse onto the same grid line.
    """
    if count <= 0:
        return []
    span = end - start
    raw = [start + span * (i + 1) / (count + 1) for i in range(count)]
    if _PORT_GRID <= 0:
        return raw
    g = _PORT_GRID
    out = []
    last = None
    for r in raw:
        v = math.floor(r / g + 0.5) * g   # half-up: stable under grid moves
        if last is not None and v <= last:
            v = last + g
        out.append(v)
        last = v
    return out


def binary_labels(n):
    """Selector labels for an N-way mux: 0/1, 00/01/10/11, ..."""
    if n <= 2:
        return [str(i) for i in range(n)]
    bits = math.ceil(math.log2(n))
    return [format(i, '0{}b'.format(bits)) for i in range(n)]


def make_primitive_ports(shape_type, n_inputs=2):
    """Default named pins for a schematic primitive block."""
    if shape_type == "mux":
        ports = [{'name': lbl, 'side': 'L', 'direction': 'in'}
                 for lbl in binary_labels(n_inputs)]
        ports.append({'name': 'sel', 'side': 'T', 'direction': 'in'})
        ports.append({'name': 'y', 'side': 'R', 'direction': 'out'})
        return ports
    if shape_type == "register":
        return [
            {'name': 'D', 'side': 'L', 'direction': 'in'},
            {'name': 'clk', 'side': 'L', 'direction': 'in'},
            {'name': 'Q', 'side': 'R', 'direction': 'out'},
        ]
    if shape_type == "adder":
        return [
            {'name': 'A', 'side': 'L', 'direction': 'in'},
            {'name': 'B', 'side': 'L', 'direction': 'in'},
            {'name': 'S', 'side': 'R', 'direction': 'out'},
        ]
    return []


# Optional "special" pins that the user can toggle on a block shape via the
# Special Pins... dialog. Each entry has a FIXED side so placement is
# consistent (enable/preset on top, clear on bottom, clock on left).
_GENERIC_SPECIAL = [
    {'name': 'en',  'side': 'T', 'direction': 'in'},
    {'name': 'set', 'side': 'T', 'direction': 'in'},
    {'name': 'clr', 'side': 'B', 'direction': 'in'},
]
# Optional clock pin, offered only on shapes that don't have a clk by default.
_CLK_PIN = {'name': 'clk', 'side': 'L', 'direction': 'in'}

STANDARD_PINS = {
    # register already has a built-in clk pin, so no clk option here.
    "register":  list(_GENERIC_SPECIAL),
    "mux":       _GENERIC_SPECIAL + [_CLK_PIN],
    "adder":     _GENERIC_SPECIAL + [_CLK_PIN],
    "rectangle": _GENERIC_SPECIAL + [_CLK_PIN],
    "square":    _GENERIC_SPECIAL + [_CLK_PIN],
    "circle":    _GENERIC_SPECIAL + [_CLK_PIN],
    "ellipse":   _GENERIC_SPECIAL + [_CLK_PIN],
    "triangle":  _GENERIC_SPECIAL + [_CLK_PIN],
}


@dataclass
class Port:
    """A named connection point (pin) on a shape's edge.

    Ports are positioned by side + declaration order, not by absolute
    coordinates, so they re-layout automatically when the parent shape is
    moved or resized. A wire endpoint binds to a port by ``name``.
    """
    name: str
    side: str = "L"            # 'L', 'R', 'T', 'B'
    direction: str = "inout"   # 'in', 'out', 'inout'

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(name=data["name"], side=data.get("side", "L"),
                   direction=data.get("direction", "inout"))


@dataclass
class Shape:
    """Base class for all drawable shapes"""
    x1: float
    y1: float
    x2: float
    y2: float
    color: str
    width: int
    shape_type: str
    shape_id: int = 0
    canvas_id: Optional[int] = None
    fill_color: Optional[str] = None
    connections: List[Dict] = field(default_factory=list)
    z_order: int = 0

    # Named ports/pins on the shape edges.
    # Stored as a list of {name, side, direction} dicts.
    ports: List[Dict] = field(default_factory=list)

    # Free-form per-primitive parameters, e.g. {"inputs": 4} for a mux.
    params: Optional[Dict] = None

    # Wire flags (apply to line/arrow/ortho_* shapes).
    # Arrowhead placement, overriding the shape-type default:
    #   None  -> default (arrow/ortho_arrow = end only; line/ortho_line = none)
    #   'none' -> no arrowheads
    #   'one'  -> arrowhead on the END only
    #   'both' -> arrowheads on BOTH the start and end
    arrow_ends: Optional[str] = None
    bus: bool = False                 # draw as a thick multi-bit bus
    slice_label: Optional[str] = None  # bit-slice tap text, e.g. "[7:0]"
    net_name: Optional[str] = None     # net label; same name = same net

    # Net label position override (px, relative to the wire's longest-segment
    # midpoint). None = use the app's current default distance. Once the
    # user drags the label, both get set to its effective (dx, dy) and that
    # offset travels with the wire from then on.
    net_label_dx: Optional[float] = None
    net_label_dy: Optional[float] = None

    # Arc-length fraction (0..1) along the wire polyline where a dragged net
    # label is anchored. None = default anchor (midpoint of longest segment).
    # Keeps the label stable when the auto-router rebuilds the wire.
    net_label_t: Optional[float] = None

    # Bit-slice tap label position override (px, relative to the tap point
    # on the wire). None = use the app's current default distance, same
    # drag-to-override behavior as the net label.
    slice_label_dx: Optional[float] = None
    slice_label_dy: Optional[float] = None

    # Off-page connector name (shape_type == "connector"). Two connectors
    # sharing this name denote the same node, including across sheets.
    conn_name: Optional[str] = None

    # Text-specific properties
    text: Optional[str] = None
    font_family: str = "Arial"
    font_size: int = 12
    font_bold: bool = False
    font_italic: bool = False
    text_align: str = "left"

    # Label properties
    label: Optional[str] = None
    label_canvas_id: Optional[int] = None
    label_offset_x: float = 0
    label_offset_y: float = 0

    # Routing for orthogonal (elbow) lines.
    # "h_first" — horizontal segment first, then vertical
    # "v_first" — vertical segment first, then horizontal
    routing: str = "h_first"

    # Intermediate waypoints for ortho lines: list of [x, y] pairs.
    # x1,y1 = start; x2,y2 = end; waypoints = everything in between.
    waypoints: list = field(default_factory=list)

    # True when the user placed waypoints by hand: honor them verbatim and
    # suppress the auto pin-approach router for this wire.
    manual_route: bool = False

    # True when the user explicitly dragged/inserted a waypoint: an absolute
    # manual override that honors waypoints even on a both-ends-pinned wire.
    user_routed: bool = False

    # True for a non-electrical annotation/leader arrow: a plain diagonal line
    # with an arrowhead that never binds to objects and is excluded from the
    # netlist, DRC, and junction-dot detection.
    annotation: bool = False

    # True to render a line/arrow dashed (legacy flag; superseded by dash_pattern).
    dashed: bool = False

    # Named dash style for a line/arrow: "" / "solid", "dashed", "fine",
    # "long", "dotted", "dash-dot". See canvas_manager.DASH_PATTERNS.
    dash_pattern: str = ""

    def to_dict(self):
        """Convert shape to dictionary for saving"""
        data = asdict(self)
        data.pop('canvas_id', None)
        return data

    @classmethod
    def from_dict(cls, data):
        """Create shape from dictionary"""
        data.pop('canvas_id', None)
        data.setdefault('routing', 'h_first')
        data.setdefault('waypoints', [])
        data.setdefault('ports', [])
        data.setdefault('arrow_ends', None)
        data.setdefault('bus', False)
        data.setdefault('slice_label', None)
        data.setdefault('net_name', None)
        data.setdefault('net_label_dx', None)
        data.setdefault('net_label_dy', None)
        data.setdefault('net_label_t', None)
        data.setdefault('slice_label_dx', None)
        data.setdefault('slice_label_dy', None)
        data.setdefault('conn_name', None)
        data.setdefault('manual_route', False)
        data.setdefault('user_routed', False)
        data.setdefault('annotation', False)
        data.setdefault('dashed', False)
        data.setdefault('dash_pattern', "")
        return cls(**data)

    def get_bounds(self):
        """Get bounding box of shape"""
        return (
            min(self.x1, self.x2),
            min(self.y1, self.y2),
            max(self.x1, self.x2),
            max(self.y1, self.y2)
        )

    def copy(self):
        """Create a copy of this shape"""
        data = self.to_dict()
        data['x1'] += 20
        data['y1'] += 20
        data['x2'] += 20
        data['y2'] += 20
        data['connections'] = []
        data['waypoints'] = [[wp[0] + 20, wp[1] + 20] for wp in data['waypoints']]
        data['ports'] = [dict(p) for p in data.get('ports', [])]
        return Shape.from_dict(data)

    # ------------------------------------------------------------------
    # Ports / pins
    # ------------------------------------------------------------------

    def ports_on_side(self, side):
        """Ports on a given side ('L'/'R'/'T'/'B'), in declared order."""
        return [p for p in self.ports if p.get('side') == side]

    def port_anchor(self, port_name):
        """Absolute (x, y) of a named port, computed from current bounds.

        Ports are distributed evenly along their side, so they follow the
        shape automatically when it is moved or resized. Returns the shape
        center if the port is not found.
        """
        x1, y1, x2, y2 = self.get_bounds()
        port = next((p for p in self.ports if p.get('name') == port_name), None)
        if port is None:
            return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
        side = port.get('side', 'L')
        same = self.ports_on_side(side)
        idx = same.index(port)
        n = len(same)
        if side in ('L', 'R'):
            ys = edge_positions(y1, y2, n)
            return (x1 if side == 'L' else x2, ys[idx])
        xs = edge_positions(x1, x2, n)
        x = xs[idx]
        y = y1 if side == 'T' else y2
        # A mux's top and bottom edges are slanted (trapezoid), so a T/B pin
        # must ride that slope instead of sitting on the bounding-box edge —
        # otherwise it floats above/below the footprint. Match the inset used
        # when drawing the mux body.
        if self.shape_type == 'mux':
            inset = min(20, abs(y2 - y1) * 0.18)
            w = (x2 - x1) or 1
            frac = (x - x1) / w
            if side == 'T':
                y = y1 + inset * frac
            else:  # 'B'
                y = y2 - inset * frac
        return (x, y)

    def port_lead(self, port_name, lead=None):
        """Tip of a pin's lead stub — the point wires actually attach to.

        Offset outward from the edge anchor by one grid cell (or 20px when
        snapping is off), keeping the tip grid-aligned.
        """
        ax, ay = self.port_anchor(port_name)
        port = next((p for p in self.ports if p.get('name') == port_name), None)
        if port is None:
            return (ax, ay)
        dx, dy = PORT_OUTWARD.get(port.get('side', 'L'), (-1, 0))
        if lead is None:
            lead = port_lead_length()
        return (ax + dx * lead, ay + dy * lead)
