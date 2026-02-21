# ============================================================================
# FILE: canvas_manager.py
# ============================================================================
"""
Canvas operations and shape management
"""
import tkinter as tk
import math
from shapes import Shape, Connection

# All shape types that behave as connectable line segments
LINE_TYPES = ("line", "arrow", "ortho_line", "ortho_arrow")


class CanvasManager:
    """Manages canvas operations and shapes"""

    def __init__(self, app):
        self.app = app
        self.shapes = []
        self.next_shape_id = 1
        self.selected_shape = None
        self.clipboard = None
        self.undo_stack = []
        self.redo_stack = []
        self.max_undo = 50

        self.editing_endpoint = None
        self.drag_data = {"x": 0, "y": 0}
        self.temp_shape = None
        self.snap_distance = 15

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

    # ------------------------------------------------------------------
    # Shape lifecycle
    # ------------------------------------------------------------------

    def add_shape(self, shape, record_undo=True):
        if shape.shape_id == 0:
            shape.shape_id = self.next_shape_id
            self.next_shape_id += 1
        self.draw_shape(shape)
        self.shapes.append(shape)
        if record_undo:
            self.record_state()

    def draw_shape(self, shape):
        canvas = self.app.canvas

        if shape.shape_type == "line":
            shape.canvas_id = canvas.create_line(
                shape.x1, shape.y1, shape.x2, shape.y2,
                fill=shape.color, width=shape.width, tags="shape"
            )

        elif shape.shape_type == "arrow":
            shape.canvas_id = canvas.create_line(
                shape.x1, shape.y1, shape.x2, shape.y2,
                fill=shape.color, width=shape.width,
                arrow=tk.LAST, arrowshape=(16, 20, 6), tags="shape"
            )

        elif shape.shape_type in ("ortho_line", "ortho_arrow"):
            all_pts = [[shape.x1, shape.y1]] + (shape.waypoints or []) + [[shape.x2, shape.y2]]
            path = self.ortho_path(all_pts, shape.routing)
            flat = [c for pt in path for c in pt]
            kw = dict(fill=shape.color, width=shape.width,
                      tags="shape", joinstyle=tk.MITER)
            if shape.shape_type == "ortho_arrow":
                kw.update(arrow=tk.LAST, arrowshape=(16, 20, 6))
            shape.canvas_id = canvas.create_line(*flat, **kw)

        elif shape.shape_type in ["rectangle", "square"]:
            shape.canvas_id = canvas.create_rectangle(
                shape.x1, shape.y1, shape.x2, shape.y2,
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
        elif shape.shape_type == "text":
            font_weight = "bold" if shape.font_bold else "normal"
            font_slant = "italic" if shape.font_italic else "roman"
            font = (shape.font_family, shape.font_size, font_weight, font_slant)
            shape.canvas_id = canvas.create_text(
                shape.x1, shape.y1,
                text=shape.text, font=font, fill=shape.color,
                anchor=tk.NW, tags="shape"
            )

        if shape.label and shape.shape_type != "text":
            cx = (shape.x1 + shape.x2) / 2
            cy = (shape.y1 + shape.y2) / 2
            shape.label_canvas_id = canvas.create_text(
                cx + shape.label_offset_x, cy + shape.label_offset_y,
                text=shape.label, font=("Arial", 10, "normal"),
                fill="black", anchor=tk.CENTER, tags="shape_label"
            )

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
            if shape.label_canvas_id:
                self.app.canvas.delete(shape.label_canvas_id)
            for s in self.shapes:
                s.connections = [c for c in s.connections
                                 if c['target_id'] != shape.shape_id]
            self.shapes.remove(shape)
            self.clear_selection()

    def clear_all(self, record_undo=True):
        if record_undo and self.shapes:
            self.record_state()
        if hasattr(self.app, 'canvas'):
            self.app.canvas.delete("shape")
            self.app.canvas.delete("shape_label")
        self.shapes.clear()
        self.clear_selection()
        self.next_shape_id = 1

    def clear_selection(self):
        self.selected_shape = None
        self.editing_endpoint = None
        if hasattr(self.app, 'canvas'):
            self.app.canvas.delete("highlight")
            self.app.canvas.delete("endpoint_handle")
            self.app.canvas.delete("label_highlight")
            self.app.canvas.delete("resize_handle")
        self.app.editing_label = False
        self.app.label_shape = None
        self.app.resizing_shape = False
        self.app.resize_handle = None
        if hasattr(self.app, 'editing_waypoint'):
            self.app.editing_waypoint = None

    def copy_shape(self):
        if self.selected_shape:
            self.clipboard = self.selected_shape.copy()
            self.app.status_bar.config(text="Shape copied")

    def paste_shape(self):
        if self.clipboard:
            new_shape = self.clipboard.copy()
            new_shape.shape_id = 0
            self.add_shape(new_shape)
            self.app.status_bar.config(text="Shape pasted")

    def bring_to_front(self):
        if self.selected_shape:
            self.app.canvas.tag_raise(self.selected_shape.canvas_id)
            self.app.status_bar.config(text="Brought to front")

    def send_to_back(self):
        if self.selected_shape:
            self.app.canvas.tag_lower(self.selected_shape.canvas_id)
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
        x, y = (line_shape.x1, line_shape.y1) if endpoint == "start" else (line_shape.x2, line_shape.y2)
        snap_x, snap_y, _ = self.get_snap_point(x, y, line_shape)
        return snap_x, snap_y

    def get_snap_point(self, x, y, exclude_shape=None):
        min_dist = self.snap_distance
        snap_x, snap_y = x, y
        snap_shape = None

        for shape in self.shapes:
            if shape == exclude_shape or shape.shape_type in LINE_TYPES:
                continue

            snap_points = []
            if shape.shape_type in ["rectangle", "square"]:
                snap_points.extend([
                    (shape.x1, shape.y1), (shape.x2, shape.y1),
                    (shape.x1, shape.y2), (shape.x2, shape.y2),
                    ((shape.x1 + shape.x2) / 2, shape.y1),
                    ((shape.x1 + shape.x2) / 2, shape.y2),
                    (shape.x1, (shape.y1 + shape.y2) / 2),
                    (shape.x2, (shape.y1 + shape.y2) / 2)
                ])
            elif shape.shape_type in ["circle", "ellipse"]:
                cx = (shape.x1 + shape.x2) / 2
                cy = (shape.y1 + shape.y2) / 2
                rx = abs(shape.x2 - shape.x1) / 2
                ry = abs(shape.y2 - shape.y1) / 2
                snap_points.extend([
                    (cx - rx, cy), (cx + rx, cy),
                    (cx, cy - ry), (cx, cy + ry)
                ])
            elif shape.shape_type == "triangle":
                cx = (shape.x1 + shape.x2) / 2
                snap_points.extend([(cx, shape.y1), (shape.x1, shape.y2), (shape.x2, shape.y2)])

            for px, py in snap_points:
                dist = math.sqrt((x - px) ** 2 + (y - py) ** 2)
                if dist < min_dist:
                    min_dist = dist
                    snap_x, snap_y = px, py
                    snap_shape = shape

        return snap_x, snap_y, snap_shape

    def redraw_shape(self, shape):
        self.app.canvas.delete(shape.canvas_id)
        if shape.label_canvas_id:
            self.app.canvas.delete(shape.label_canvas_id)
            shape.label_canvas_id = None
        self.draw_shape(shape)

    def update_connected_lines(self, moved_shape):
        for shape in self.shapes:
            if shape.shape_type not in LINE_TYPES:
                continue
            for conn in shape.connections:
                if isinstance(conn, dict) and conn.get('target_id') == moved_shape.shape_id:
                    snap_x, snap_y = self.get_connection_point(moved_shape, shape, conn['endpoint'])
                    if conn['endpoint'] == 'start':
                        shape.x1, shape.y1 = snap_x, snap_y
                    else:
                        shape.x2, shape.y2 = snap_x, snap_y
                    self.redraw_shape(shape)
