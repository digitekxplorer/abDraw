# ============================================================================
# FILE: shapes.py
# ============================================================================
"""
Shape data structures and utilities for abDraw
"""
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
import json


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
        return Shape.from_dict(data)