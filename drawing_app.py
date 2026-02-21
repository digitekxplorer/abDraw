# ============================================================================
# FILE: drawing_app.py
# ============================================================================
"""
Main application class for abDraw
"""
import tkinter as tk
from tkinter import ttk, colorchooser, messagebox
import math

from shapes import Shape
from file_manager import FileManager
from canvas_manager import CanvasManager, LINE_TYPES


class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip = None
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event=None):
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25
        self.tooltip = tk.Toplevel(self.widget)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tooltip, text=self.text, background="#FFFFE0",
                 relief=tk.SOLID, borderwidth=1, font=("Arial", 9)).pack()

    def hide_tooltip(self, event=None):
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None


class DrawingApp:
    """Main drawing application"""

    def __init__(self, root):
        self.root = root
        self.root.geometry("1200x800")

        self.file_manager = FileManager(self)
        self.canvas_manager = CanvasManager(self)

        # Drawing state
        self.current_tool = "select"
        self.current_color = "black"
        self.current_fill = ""
        self.line_width = 2

        # Grid
        self.grid_enabled = True
        self.grid_type = "dots"
        self.grid_spacing = 20
        self.snap_to_grid = True
        self.last_canvas_size = (0, 0)

        # Label editing
        self.editing_label = False
        self.label_shape = None

        # Resize state
        self.resizing_shape = False
        self.resize_handle = None
        self.resize_center = None

        # Ortho multi-click drawing state
        self.ortho_in_progress = False
        self.ortho_start = None
        self.ortho_waypoints = []

        # Ortho / line waypoint editing state (select tool)
        # Values: None | "start" | "end" | int (waypoint index)
        self.editing_waypoint = None

        self.setup_ui()
        self.setup_bindings()
        self.setup_menu()

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def setup_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="New", command=self.file_manager.new_drawing, accelerator="Ctrl+N")
        file_menu.add_command(label="Open...", command=self.file_manager.open_drawing, accelerator="Ctrl+O")
        file_menu.add_command(label="Save", command=self.file_manager.save_drawing, accelerator="Ctrl+S")
        file_menu.add_command(label="Save As...", command=self.file_manager.save_drawing_as, accelerator="Ctrl+Shift+S")
        file_menu.add_separator()
        file_menu.add_command(label="Export PNG...", command=self.file_manager.export_png)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)

        edit_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        edit_menu.add_command(label="Undo", command=self.canvas_manager.undo, accelerator="Ctrl+Z")
        edit_menu.add_command(label="Redo", command=self.canvas_manager.redo, accelerator="Ctrl+Y")
        edit_menu.add_separator()
        edit_menu.add_command(label="Copy", command=self.canvas_manager.copy_shape, accelerator="Ctrl+C")
        edit_menu.add_command(label="Paste", command=self.canvas_manager.paste_shape, accelerator="Ctrl+V")
        edit_menu.add_command(label="Delete", command=self.delete_selected, accelerator="Delete")
        edit_menu.add_separator()
        edit_menu.add_command(label="Add Label to Shape", command=self.add_label_to_selected, accelerator="Ctrl+L")
        edit_menu.add_command(label="Select All", command=self.select_all, accelerator="Ctrl+A")

        arrange_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Arrange", menu=arrange_menu)
        arrange_menu.add_command(label="Bring to Front", command=self.canvas_manager.bring_to_front)
        arrange_menu.add_command(label="Send to Back", command=self.canvas_manager.send_to_back)

        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        self.grid_enabled_var = tk.BooleanVar(value=True)
        view_menu.add_checkbutton(label="Show Grid", variable=self.grid_enabled_var,
                                  command=self.toggle_grid, accelerator="Ctrl+G")
        self.snap_enabled_var = tk.BooleanVar(value=True)
        view_menu.add_checkbutton(label="Snap to Grid", variable=self.snap_enabled_var,
                                  command=self.toggle_snap, accelerator="Ctrl+H")
        view_menu.add_separator()

        grid_type_menu = tk.Menu(view_menu, tearoff=0)
        view_menu.add_cascade(label="Grid Type", menu=grid_type_menu)
        self.grid_type_var = tk.StringVar(value="dots")
        grid_type_menu.add_radiobutton(label="Lines", variable=self.grid_type_var,
                                       value="lines", command=self.change_grid_type)
        grid_type_menu.add_radiobutton(label="Dots", variable=self.grid_type_var,
                                       value="dots", command=self.change_grid_type)

        grid_spacing_menu = tk.Menu(view_menu, tearoff=0)
        view_menu.add_cascade(label="Grid Spacing", menu=grid_spacing_menu)
        self.grid_spacing_var = tk.IntVar(value=20)
        for spacing in [10, 20, 30, 40, 50]:
            grid_spacing_menu.add_radiobutton(label=f"{spacing} pixels",
                                              variable=self.grid_spacing_var,
                                              value=spacing, command=self.change_grid_spacing)

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def setup_ui(self):
        self.status_bar = ttk.Label(self.root, text="Ready | Grid: ON | Snap: ON",
                                    relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        main_frame = ttk.Frame(self.root)
        main_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.setup_toolbar(main_frame)

        canvas_frame = ttk.Frame(main_frame)
        canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.canvas = tk.Canvas(canvas_frame, bg="white", cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.select_tool("select")
        self.draw_grid()
        self.canvas.bind("<Configure>", self.on_canvas_resize)

    def setup_toolbar(self, parent):
        toolbar = ttk.Frame(parent, relief=tk.RAISED, borderwidth=2)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        btn_new = ttk.Button(toolbar, text="📁 New", command=self.file_manager.new_drawing, width=8)
        btn_new.pack(side=tk.LEFT, padx=2)
        ToolTip(btn_new, "New drawing (Ctrl+N)")
        btn_open = ttk.Button(toolbar, text="📂 Open", command=self.file_manager.open_drawing, width=8)
        btn_open.pack(side=tk.LEFT, padx=2)
        ToolTip(btn_open, "Open drawing (Ctrl+O)")
        btn_save = ttk.Button(toolbar, text="💾 Save", command=self.file_manager.save_drawing, width=8)
        btn_save.pack(side=tk.LEFT, padx=2)
        ToolTip(btn_save, "Save drawing (Ctrl+S)")

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=10, fill=tk.Y)

        btn_undo = ttk.Button(toolbar, text="↶ Undo", command=self.canvas_manager.undo, width=8)
        btn_undo.pack(side=tk.LEFT, padx=2)
        ToolTip(btn_undo, "Undo (Ctrl+Z)")
        btn_redo = ttk.Button(toolbar, text="↷ Redo", command=self.canvas_manager.redo, width=8)
        btn_redo.pack(side=tk.LEFT, padx=2)
        ToolTip(btn_redo, "Redo (Ctrl+Y)")

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=10, fill=tk.Y)

        tools = [
            ("Select",      "select",      "🖱️",  "Select and move shapes"),
            ("Line",        "line",        "📏",  "Draw line"),
            ("Arrow",       "arrow",       "➡️",  "Draw arrow"),
            ("Ortho Line",  "ortho_line",  "⌐",
             "Draw line with 90° turns — left-click to add turns, right-click or Enter to finish, Esc to cancel"),
            ("Ortho Arrow", "ortho_arrow", "⌐→",
             "Draw arrow with 90° turns — left-click to add turns, right-click or Enter to finish, Esc to cancel"),
            ("Rectangle",   "rectangle",   "⬜",  "Draw rectangle"),
            ("Square",      "square",      "◻️",  "Draw square"),
            ("Circle",      "circle",      "⭕",  "Draw circle"),
            ("Ellipse",     "ellipse",     "⬭",   "Draw ellipse"),
            ("Triangle",    "triangle",    "🔺",  "Draw triangle"),
            ("Text",        "text",        "T",   "Add text label"),
        ]

        self.tool_buttons = {}
        for name, tool, icon, tooltip_text in tools:
            btn = ttk.Button(toolbar, text=icon, command=lambda t=tool: self.select_tool(t), width=3)
            btn.pack(side=tk.LEFT, padx=1)
            self.tool_buttons[tool] = btn
            ToolTip(btn, tooltip_text)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=10, fill=tk.Y)

        self.color_btn = tk.Button(toolbar, text="●", bg=self.current_color,
                                   command=self.choose_color, width=3, font=("Arial", 16))
        self.color_btn.pack(side=tk.LEFT, padx=2)
        ToolTip(self.color_btn, "Choose color")

        ttk.Label(toolbar, text="Width:").pack(side=tk.LEFT, padx=5)
        self.width_var = tk.IntVar(value=2)
        width_spin = ttk.Spinbox(toolbar, from_=1, to=10, width=5,
                                 textvariable=self.width_var, command=self.update_width)
        width_spin.pack(side=tk.LEFT, padx=2)
        ToolTip(width_spin, "Line width (1-10)")

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=10, fill=tk.Y)

        btn_delete = ttk.Button(toolbar, text="🗑️ Delete", command=self.delete_selected)
        btn_delete.pack(side=tk.LEFT, padx=2)
        ToolTip(btn_delete, "Delete selected shape (Delete key)")

    def setup_bindings(self):
        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<Button-3>", self.on_right_click)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Double-Button-1>", self.on_double_click)
        self.canvas.bind("<Motion>", self.on_mouse_move)

        self.root.bind("<Control-n>", lambda e: self.file_manager.new_drawing())
        self.root.bind("<Control-o>", lambda e: self.file_manager.open_drawing())
        self.root.bind("<Control-s>", lambda e: self.file_manager.save_drawing())
        self.root.bind("<Control-z>", lambda e: self.canvas_manager.undo())
        self.root.bind("<Control-y>", lambda e: self.canvas_manager.redo())
        self.root.bind("<Control-c>", lambda e: self.canvas_manager.copy_shape())
        self.root.bind("<Control-v>", lambda e: self.canvas_manager.paste_shape())
        self.root.bind("<Delete>", lambda e: self.delete_selected())
        self.root.bind("<Control-g>", lambda e: self.toggle_grid_shortcut())
        self.root.bind("<Control-h>", lambda e: self.toggle_snap_shortcut())
        self.root.bind("<Control-l>", lambda e: self.add_label_to_selected())
        self.root.bind("<Escape>", lambda e: self.deselect_all())
        self.root.bind("<Return>", lambda e: self._finish_ortho_if_active())
        self.root.bind("<r>", lambda e: self._flip_ortho_routing())
        self.root.bind("<R>", lambda e: self._flip_ortho_routing())

    # ------------------------------------------------------------------
    # Tool selection
    # ------------------------------------------------------------------

    def select_tool(self, tool):
        if self.ortho_in_progress:
            self._cancel_ortho_drawing()

        self.current_tool = tool
        self.canvas_manager.clear_selection()
        self.editing_label = False
        self.label_shape = None
        self.canvas.delete("label_highlight")
        self.resizing_shape = False
        self.resize_handle = None
        self.resize_center = None

        for t, btn in self.tool_buttons.items():
            btn.state(['pressed'] if t == tool else ['!pressed'])

        if tool in ("ortho_line", "ortho_arrow"):
            self.status_bar.config(
                text=f"Tool: {tool} — left-click to place points, "
                     f"right-click or Enter to finish, Esc to cancel"
            )
        else:
            self.status_bar.config(text=f"Tool: {tool.capitalize()}")

    def choose_color(self):
        color = colorchooser.askcolor(initialcolor=self.current_color)[1]
        if color:
            self.current_color = color
            self.color_btn.config(bg=color)

    def update_width(self):
        self.line_width = self.width_var.get()

    # ------------------------------------------------------------------
    # Ortho drawing helpers
    # ------------------------------------------------------------------

    def _flip_ortho_routing(self):
        """Flip h_first / v_first on the selected ortho line (press R)."""
        sel = self.canvas_manager.selected_shape
        if sel and sel.shape_type in ("ortho_line", "ortho_arrow"):
            self.canvas_manager.flip_routing(sel)

    def _cancel_ortho_drawing(self):
        """Abort an in-progress ortho line."""
        self.ortho_in_progress = False
        self.ortho_start = None
        self.ortho_waypoints = []
        self.canvas.delete("ortho_preview")

    def _update_ortho_preview(self, mouse_x, mouse_y):
        """Redraw the dashed preview line from start through waypoints to mouse."""
        self.canvas.delete("ortho_preview")
        if not self.ortho_in_progress or not self.ortho_start:
            return
        all_pts = [self.ortho_start] + self.ortho_waypoints + [[mouse_x, mouse_y]]
        path = CanvasManager.ortho_path(all_pts, "h_first")
        flat = [c for pt in path for c in pt]
        if len(flat) < 4:
            return
        kw = dict(fill=self.current_color, width=self.line_width,
                  dash=(4, 4), joinstyle=tk.MITER, tags="ortho_preview")
        if self.current_tool == "ortho_arrow":
            kw.update(arrow=tk.LAST, arrowshape=(16, 20, 6))
        self.canvas.create_line(*flat, **kw)

    def _finalize_ortho_line(self, end_x, end_y):
        """Create the final ortho Shape from all accumulated points."""
        x1, y1 = self.ortho_start
        waypoints = [list(wp) for wp in self.ortho_waypoints]

        self.canvas.delete("ortho_preview")
        self.ortho_in_progress = False
        self.ortho_start = None
        self.ortho_waypoints = []

        if abs(end_x - x1) < 3 and abs(end_y - y1) < 3 and not waypoints:
            return  # Too small — ignore

        shape = Shape(
            x1=x1, y1=y1, x2=end_x, y2=end_y,
            color=self.current_color, width=self.line_width,
            shape_type=self.current_tool, fill_color=self.current_fill,
            routing="h_first", waypoints=waypoints
        )
        self.canvas_manager.add_shape(shape)
        n = len(waypoints)
        self.status_bar.config(
            text=f"Added {self.current_tool} with {n} waypoint{'s' if n != 1 else ''} "
                 f"— left-click to place points, right-click or Enter to finish"
        )

    def _finish_ortho_if_active(self):
        """Enter key: finalize using the last placed waypoint as the endpoint."""
        if not self.ortho_in_progress:
            return
        if self.ortho_waypoints:
            last = self.ortho_waypoints.pop()
            self._finalize_ortho_line(last[0], last[1])
        elif self.ortho_start:
            # No waypoints yet — cancel rather than create a zero-length line
            self._cancel_ortho_drawing()
            self.status_bar.config(text="Drawing cancelled — need at least one turn or endpoint")

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def on_mouse_move(self, event):
        """Update ortho preview on plain mouse movement (no button held)."""
        if self.ortho_in_progress:
            x, y = event.x, event.y
            if self.snap_to_grid:
                x, y = self.snap_point(x, y)
            self._update_ortho_preview(x, y)

    def on_right_click(self, event):
        """Right-click: finalize an in-progress ortho line at the cursor position."""
        if self.ortho_in_progress:
            x, y = event.x, event.y
            if self.snap_to_grid:
                x, y = self.snap_point(x, y)
            self._finalize_ortho_line(x, y)

    def on_press(self, event):
        x, y = event.x, event.y

        # --- Ortho click-to-place drawing ---
        if self.current_tool in ("ortho_line", "ortho_arrow"):
            if self.snap_to_grid:
                x, y = self.snap_point(x, y)
            if not self.ortho_in_progress:
                # First click — set start point
                self.ortho_in_progress = True
                self.ortho_start = [x, y]
                self.ortho_waypoints = []
                self.status_bar.config(
                    text="Click to add turns — right-click or Enter to finish | Esc to cancel"
                )
            else:
                # Subsequent clicks — add waypoint
                self.ortho_waypoints.append([x, y])
                n = len(self.ortho_waypoints)
                self.status_bar.config(
                    text=f"{n} waypoint{'s' if n != 1 else ''} placed — "
                         f"right-click or Enter to finish | Esc to cancel"
                )
            return

        # Snap for regular drawing tools
        if self.current_tool != "select" and self.snap_to_grid:
            x, y = self.snap_point(x, y)

        if self.current_tool == "text":
            self.create_text_at_position(x, y)
            return

        if self.current_tool == "select":
            # 1. Resize handle?
            items = self.canvas.find_overlapping(x - 3, y - 3, x + 3, y + 3)
            for item in reversed(items):
                tags = self.canvas.gettags(item)
                if "resize_handle" in tags:
                    for tag in tags:
                        if tag.endswith("_handle") and tag != "resize_handle":
                            self.resizing_shape = True
                            self.resize_handle = tag.replace("_handle", "")
                            self.canvas_manager.drag_data = {"x": x, "y": y}
                            shape = self.canvas_manager.selected_shape
                            if shape and shape.shape_type in ("circle", "ellipse"):
                                self.resize_center = (
                                    (shape.x1 + shape.x2) / 2.0,
                                    (shape.y1 + shape.y2) / 2.0
                                )
                            else:
                                self.resize_center = None
                            self.status_bar.config(text="Resizing — drag to adjust size")
                            return

            # 2. Shape label?
            for item in reversed(items):
                if "shape_label" in self.canvas.gettags(item):
                    for shape in self.canvas_manager.shapes:
                        if shape.label_canvas_id == item:
                            self.editing_label = True
                            self.label_shape = shape
                            self.canvas_manager.drag_data = {"x": x, "y": y}
                            bbox = self.canvas.bbox(item)
                            if bbox:
                                self.canvas.delete("label_highlight")
                                self.canvas.create_rectangle(
                                    bbox[0] - 3, bbox[1] - 3, bbox[2] + 3, bbox[3] + 3,
                                    outline="orange", dash=(3, 3), width=2, tags="label_highlight"
                                )
                            self.status_bar.config(text="Moving label — drag to reposition")
                            return

            # 3. Ortho waypoint handle?
            for item in items:
                tags = self.canvas.gettags(item)
                for tag in tags:
                    if tag == "ortho_start_handle":
                        self.editing_waypoint = "start"
                        self.canvas_manager.drag_data = {"x": x, "y": y}
                        self.status_bar.config(text="Dragging start point")
                        return
                    elif tag == "ortho_end_handle":
                        self.editing_waypoint = "end"
                        self.canvas_manager.drag_data = {"x": x, "y": y}
                        self.status_bar.config(text="Dragging end point")
                        return
                    elif tag.startswith("ortho_wp_") and tag.endswith("_handle"):
                        try:
                            idx = int(tag[9:-7])
                            self.editing_waypoint = idx
                            self.canvas_manager.drag_data = {"x": x, "y": y}
                            self.status_bar.config(text=f"Dragging waypoint {idx + 1}")
                            return
                        except ValueError:
                            pass

            # 4. Regular line endpoint handle?
            for item in items:
                tags = self.canvas.gettags(item)
                if "start_handle" in tags:
                    self.canvas_manager.editing_endpoint = "start"
                    self.canvas_manager.drag_data = {"x": x, "y": y}
                    self.status_bar.config(text="Editing start point — drag to connect")
                    return
                elif "end_handle" in tags:
                    self.canvas_manager.editing_endpoint = "end"
                    self.canvas_manager.drag_data = {"x": x, "y": y}
                    self.status_bar.config(text="Editing end point — drag to connect")
                    return

            # 5. Regular shape selection
            self.handle_selection(x, y)
            if self.canvas_manager.selected_shape:
                self.canvas_manager.drag_data = {"x": x, "y": y, "start_x": x, "start_y": y}
        else:
            self.canvas_manager.drag_data = {"x": x, "y": y}

    def on_drag(self, event):
        x, y = event.x, event.y

        # Ortho preview during drag (button held after placing a point)
        if self.ortho_in_progress:
            draw_x, draw_y = (self.snap_point(x, y) if self.snap_to_grid else (x, y))
            self._update_ortho_preview(draw_x, draw_y)
            return

        if self.current_tool == "select":
            # Resize
            if self.resizing_shape and self.canvas_manager.selected_shape:
                shape = self.canvas_manager.selected_shape
                if self.snap_to_grid:
                    x, y = self.snap_point(x, y)

                if shape.shape_type == "square":
                    if self.resize_handle == 'nw':   shape.x1, shape.y1 = x, y
                    elif self.resize_handle == 'ne': shape.x2, shape.y1 = x, y
                    elif self.resize_handle == 'sw': shape.x1, shape.y2 = x, y
                    elif self.resize_handle == 'se': shape.x2, shape.y2 = x, y
                    size = max(abs(shape.x2 - shape.x1), abs(shape.y2 - shape.y1))
                    if self.resize_handle == 'se':
                        shape.x2 = shape.x1 + (size if shape.x2 > shape.x1 else -size)
                        shape.y2 = shape.y1 + (size if shape.y2 > shape.y1 else -size)
                    elif self.resize_handle == 'nw':
                        shape.x1 = shape.x2 - (size if shape.x2 > shape.x1 else -size)
                        shape.y1 = shape.y2 - (size if shape.y2 > shape.y1 else -size)
                    elif self.resize_handle == 'ne':
                        shape.x2 = shape.x1 + (size if shape.x2 > shape.x1 else -size)
                        shape.y1 = shape.y2 - (size if shape.y2 > shape.y1 else -size)
                    elif self.resize_handle == 'sw':
                        shape.x1 = shape.x2 - (size if shape.x2 > shape.x1 else -size)
                        shape.y2 = shape.y1 + (size if shape.y2 > shape.y1 else -size)
                elif shape.shape_type == "circle":
                    cx, cy = self.resize_center
                    radius = max(math.sqrt((x - cx) ** 2 + (y - cy) ** 2), 5)
                    shape.x1, shape.y1, shape.x2, shape.y2 = cx-radius, cy-radius, cx+radius, cy+radius
                elif shape.shape_type == "ellipse":
                    cx, cy = self.resize_center
                    rx = max(abs(x - cx) if self.resize_handle in ('ne', 'se') else abs(cx - x), 5)
                    ry = max(abs(y - cy) if self.resize_handle in ('sw', 'se') else abs(cy - y), 5)
                    shape.x1, shape.y1, shape.x2, shape.y2 = cx-rx, cy-ry, cx+rx, cy+ry
                else:
                    if self.resize_handle == 'nw':   shape.x1, shape.y1 = x, y
                    elif self.resize_handle == 'ne': shape.x2, shape.y1 = x, y
                    elif self.resize_handle == 'sw': shape.x1, shape.y2 = x, y
                    elif self.resize_handle == 'se': shape.x2, shape.y2 = x, y

                self.canvas_manager.redraw_shape(shape)
                self.canvas.delete("resize_handle")
                self.draw_resize_handles(shape)
                self.canvas.delete("highlight")
                coords = [shape.x1, shape.y1, shape.x2, shape.y2]
                self.canvas.create_rectangle(
                    min(coords[0::2]) - 5, min(coords[1::2]) - 5,
                    max(coords[0::2]) + 5, max(coords[1::2]) + 5,
                    outline="blue", dash=(5, 5), width=2, tags="highlight"
                )
                self.file_manager.mark_modified()
                return

            # Label drag
            if self.editing_label and self.label_shape:
                dx = x - self.canvas_manager.drag_data["x"]
                dy = y - self.canvas_manager.drag_data["y"]
                self.canvas.move(self.label_shape.label_canvas_id, dx, dy)
                self.canvas.move("label_highlight", dx, dy)
                self.label_shape.label_offset_x += dx
                self.label_shape.label_offset_y += dy
                self.canvas_manager.drag_data["x"] = x
                self.canvas_manager.drag_data["y"] = y
                self.file_manager.mark_modified()
                return

            # Ortho waypoint drag
            if self.editing_waypoint is not None and self.canvas_manager.selected_shape:
                shape = self.canvas_manager.selected_shape

                if self.editing_waypoint in ("start", "end"):
                    # Endpoints participate in shape snapping
                    snap_x, snap_y, snap_shape = self.canvas_manager.get_snap_point(x, y, shape)
                    if not snap_shape and self.snap_to_grid:
                        snap_x, snap_y = self.snap_point(x, y)
                    if self.editing_waypoint == "start":
                        shape.x1, shape.y1 = snap_x, snap_y
                    else:
                        shape.x2, shape.y2 = snap_x, snap_y
                    # Show/hide snap indicator
                    self.canvas.delete("snap_indicator")
                    if snap_shape:
                        self.canvas.create_oval(
                            snap_x - 8, snap_y - 8, snap_x + 8, snap_y + 8,
                            outline="blue", width=2, dash=(2, 2), tags="snap_indicator"
                        )
                else:
                    # Interior waypoints snap to grid only
                    if self.snap_to_grid:
                        x, y = self.snap_point(x, y)
                    shape.waypoints[self.editing_waypoint] = [x, y]

                self.canvas_manager.redraw_shape(shape)
                self.canvas.delete("endpoint_handle")
                self.draw_ortho_handles(shape)
                self.canvas.delete("highlight")
                all_x = [shape.x1, shape.x2] + [wp[0] for wp in shape.waypoints]
                all_y = [shape.y1, shape.y2] + [wp[1] for wp in shape.waypoints]
                self.canvas.create_rectangle(
                    min(all_x) - 5, min(all_y) - 5, max(all_x) + 5, max(all_y) + 5,
                    outline="blue", dash=(5, 5), width=2, tags="highlight"
                )
                self.file_manager.mark_modified()
                return

            # Regular line endpoint drag
            if self.canvas_manager.editing_endpoint and self.canvas_manager.selected_shape:
                snap_x, snap_y, snap_shape = self.canvas_manager.get_snap_point(
                    x, y, self.canvas_manager.selected_shape)
                if not snap_shape and self.snap_to_grid:
                    snap_x, snap_y = self.snap_point(x, y)
                if self.canvas_manager.editing_endpoint == "start":
                    self.canvas_manager.selected_shape.x1 = snap_x
                    self.canvas_manager.selected_shape.y1 = snap_y
                else:
                    self.canvas_manager.selected_shape.x2 = snap_x
                    self.canvas_manager.selected_shape.y2 = snap_y
                self.canvas_manager.redraw_shape(self.canvas_manager.selected_shape)
                self.canvas.delete("endpoint_handle")
                self.draw_endpoint_handles(self.canvas_manager.selected_shape)
                self.canvas.delete("snap_indicator")
                if snap_shape:
                    self.canvas.create_oval(snap_x - 8, snap_y - 8, snap_x + 8, snap_y + 8,
                                            outline="blue", width=2, dash=(2, 2), tags="snap_indicator")
                return

            # Move selected shape
            if (self.canvas_manager.selected_shape
                    and not self.canvas_manager.editing_endpoint
                    and not self.resizing_shape
                    and self.editing_waypoint is None):
                dx = x - self.canvas_manager.drag_data["x"]
                dy = y - self.canvas_manager.drag_data["y"]
                shape = self.canvas_manager.selected_shape
                self.canvas.move(shape.canvas_id, dx, dy)
                self.canvas.move("highlight", dx, dy)
                self.canvas.move("endpoint_handle", dx, dy)
                self.canvas.move("resize_handle", dx, dy)
                if shape.label_canvas_id:
                    self.canvas.move(shape.label_canvas_id, dx, dy)
                shape.x1 += dx;  shape.y1 += dy
                if shape.shape_type == "text":
                    shape.x2 = shape.x1;  shape.y2 = shape.y1
                else:
                    shape.x2 += dx;  shape.y2 += dy
                for wp in shape.waypoints:
                    wp[0] += dx;  wp[1] += dy
                self.canvas_manager.update_connected_lines(shape)
                self.canvas_manager.drag_data["x"] = x
                self.canvas_manager.drag_data["y"] = y
                self.file_manager.mark_modified()
        else:
            # Preview for regular (non-ortho) drawing tools
            draw_x, draw_y = (self.snap_point(x, y) if self.snap_to_grid else (x, y))
            if self.canvas_manager.temp_shape:
                self.canvas.delete(self.canvas_manager.temp_shape)
            self.canvas_manager.temp_shape = self.draw_preview(
                self.canvas_manager.drag_data["x"],
                self.canvas_manager.drag_data["y"],
                draw_x, draw_y
            )

    def on_release(self, event):
        x, y = event.x, event.y

        # Ortho lines finalize via right-click or Enter — ignore release
        if self.current_tool in ("ortho_line", "ortho_arrow") and self.ortho_in_progress:
            return

        if self.current_tool != "select" and self.snap_to_grid:
            x, y = self.snap_point(x, y)

        if self.current_tool == "select":
            if self.resizing_shape:
                self.resizing_shape = False
                self.resize_handle = None
                self.resize_center = None
                self.canvas_manager.record_state()
                self.status_bar.config(text="Shape resized")
                return

            if self.editing_label:
                self.canvas.delete("label_highlight")
                self.editing_label = False
                self.canvas_manager.record_state()
                self.label_shape = None
                self.status_bar.config(text="Label repositioned")
                return

            if self.editing_waypoint is not None:
                shape = self.canvas_manager.selected_shape
                if self.editing_waypoint in ("start", "end") and shape:
                    # Check for shape snap and update connections
                    ex = shape.x1 if self.editing_waypoint == "start" else shape.x2
                    ey = shape.y1 if self.editing_waypoint == "start" else shape.y2
                    _, _, snap_shape = self.canvas_manager.get_snap_point(ex, ey, shape)
                    if snap_shape:
                        shape.connections = [c for c in shape.connections
                                             if c.get('endpoint') != self.editing_waypoint]
                        shape.connections.append({
                            'target_id': snap_shape.shape_id,
                            'endpoint': self.editing_waypoint
                        })
                        self.status_bar.config(
                            text=f"Connected {self.editing_waypoint} to shape")
                    else:
                        shape.connections = [c for c in shape.connections
                                             if c.get('endpoint') != self.editing_waypoint]
                        self.status_bar.config(text="Point moved")
                    self.canvas.delete("snap_indicator")
                else:
                    self.status_bar.config(text="Waypoint moved")
                self.editing_waypoint = None
                self.canvas_manager.record_state()
                return

            if self.canvas_manager.editing_endpoint and self.canvas_manager.selected_shape:
                snap_x, snap_y, snap_shape = self.canvas_manager.get_snap_point(
                    x, y, self.canvas_manager.selected_shape)
                if not snap_shape and self.snap_to_grid:
                    snap_x, snap_y = self.snap_point(x, y)
                if snap_shape:
                    self.canvas_manager.selected_shape.connections = [
                        c for c in self.canvas_manager.selected_shape.connections
                        if c.get('endpoint') != self.canvas_manager.editing_endpoint
                    ]
                    self.canvas_manager.selected_shape.connections.append({
                        'target_id': snap_shape.shape_id,
                        'endpoint': self.canvas_manager.editing_endpoint
                    })
                    self.status_bar.config(
                        text=f"Connected {self.canvas_manager.editing_endpoint} to shape")
                else:
                    self.canvas_manager.selected_shape.connections = [
                        c for c in self.canvas_manager.selected_shape.connections
                        if c.get('endpoint') != self.canvas_manager.editing_endpoint
                    ]
                self.canvas.delete("snap_indicator")
                self.canvas_manager.editing_endpoint = None
                self.canvas_manager.record_state()
                self.file_manager.mark_modified()
                return

            if self.canvas_manager.selected_shape:
                start_x = self.canvas_manager.drag_data.get("start_x", x)
                start_y = self.canvas_manager.drag_data.get("start_y", y)
                if abs(x - start_x) > 2 or abs(y - start_y) > 2:
                    if self.snap_to_grid:
                        shape = self.canvas_manager.selected_shape
                        snapped_x1, snapped_y1 = self.snap_point(shape.x1, shape.y1)
                        snap_dx = snapped_x1 - shape.x1
                        snap_dy = snapped_y1 - shape.y1
                        if abs(snap_dx) > 0.1 or abs(snap_dy) > 0.1:
                            self.canvas.move(shape.canvas_id, snap_dx, snap_dy)
                            self.canvas.move("highlight", snap_dx, snap_dy)
                            self.canvas.move("endpoint_handle", snap_dx, snap_dy)
                            if shape.label_canvas_id:
                                self.canvas.move(shape.label_canvas_id, snap_dx, snap_dy)
                            shape.x1 = snapped_x1;  shape.y1 = snapped_y1
                            if shape.shape_type == "text":
                                shape.x2 = snapped_x1;  shape.y2 = snapped_y1
                            else:
                                shape.x2 += snap_dx;  shape.y2 += snap_dy
                            for wp in shape.waypoints:
                                wp[0] += snap_dx;  wp[1] += snap_dy
                            self.canvas_manager.update_connected_lines(shape)
                    self.canvas_manager.record_state()
        else:
            if self.current_tool != "text":
                if self.canvas_manager.temp_shape:
                    self.canvas.delete(self.canvas_manager.temp_shape)
                    self.canvas_manager.temp_shape = None
                shape = self.create_shape(
                    self.canvas_manager.drag_data["x"],
                    self.canvas_manager.drag_data["y"],
                    x, y
                )
                if shape:
                    self.canvas_manager.add_shape(shape)

    def on_double_click(self, event):
        """Double-click: edit text shapes only.
        Ortho lines are finalized via right-click or Enter — not double-click."""
        if self.current_tool != "select":
            return
        x, y = event.x, event.y
        items = self.canvas.find_overlapping(x - 5, y - 5, x + 5, y + 5)
        for item in reversed(items):
            if "shape" in self.canvas.gettags(item):
                for shape in self.canvas_manager.shapes:
                    if shape.canvas_id == item and shape.shape_type == "text":
                        self.edit_text_shape(shape)
                        return

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def draw_preview(self, x1, y1, x2, y2):
        """Draw preview for regular (single-gesture) drawing tools."""
        if self.current_tool == "line":
            return self.canvas.create_line(x1, y1, x2, y2,
                                           fill=self.current_color, width=self.line_width, dash=(4, 4))
        elif self.current_tool == "arrow":
            return self.canvas.create_line(x1, y1, x2, y2, fill=self.current_color,
                                           width=self.line_width, arrow=tk.LAST,
                                           arrowshape=(16, 20, 6), dash=(4, 4))
        elif self.current_tool == "rectangle":
            return self.canvas.create_rectangle(x1, y1, x2, y2, outline=self.current_color,
                                                width=self.line_width, dash=(4, 4))
        elif self.current_tool == "square":
            size = max(abs(x2 - x1), abs(y2 - y1))
            x2 = x1 + size if x2 > x1 else x1 - size
            y2 = y1 + size if y2 > y1 else y1 - size
            return self.canvas.create_rectangle(x1, y1, x2, y2, outline=self.current_color,
                                                width=self.line_width, dash=(4, 4))
        elif self.current_tool == "circle":
            r = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
            return self.canvas.create_oval(x1 - r, y1 - r, x1 + r, y1 + r,
                                           outline=self.current_color, width=self.line_width, dash=(4, 4))
        elif self.current_tool == "ellipse":
            return self.canvas.create_oval(x1, y1, x2, y2, outline=self.current_color,
                                           width=self.line_width, dash=(4, 4))
        elif self.current_tool == "triangle":
            cx = (x1 + x2) / 2
            return self.canvas.create_polygon(cx, y1, x1, y2, x2, y2, outline=self.current_color,
                                              fill="", width=self.line_width, dash=(4, 4))
        return None

    def create_shape(self, x1, y1, x2, y2):
        """Create a new non-ortho shape from a drag gesture."""
        if abs(x2 - x1) < 3 and abs(y2 - y1) < 3:
            return None
        if self.current_tool == "circle":
            r = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
            x1, y1, x2, y2 = x1 - r, y1 - r, x1 + r, y1 + r
        elif self.current_tool == "square":
            size = max(abs(x2 - x1), abs(y2 - y1))
            x2 = x1 + size if x2 > x1 else x1 - size
            y2 = y1 + size if y2 > y1 else y1 - size
        return Shape(x1=x1, y1=y1, x2=x2, y2=y2,
                     color=self.current_color, width=self.line_width,
                     shape_type=self.current_tool, fill_color=self.current_fill)

    # ------------------------------------------------------------------
    # Selection & handles
    # ------------------------------------------------------------------

    def handle_selection(self, x, y):
        self.canvas_manager.clear_selection()
        self.editing_label = False
        self.label_shape = None

        items = self.canvas.find_overlapping(x - 5, y - 5, x + 5, y + 5)
        for item in reversed(items):
            if "shape" in self.canvas.gettags(item):
                for shape in self.canvas_manager.shapes:
                    if shape.canvas_id == item:
                        self.canvas_manager.selected_shape = shape

                        if shape.shape_type == "text":
                            bbox = self.canvas.bbox(item)
                            if bbox:
                                self.canvas.create_rectangle(
                                    bbox[0] - 5, bbox[1] - 5, bbox[2] + 5, bbox[3] + 5,
                                    outline="blue", dash=(5, 5), width=2, tags="highlight"
                                )
                        else:
                            coords = self.canvas.coords(item)
                            if len(coords) >= 4:
                                self.canvas.create_rectangle(
                                    min(coords[0::2]) - 5, min(coords[1::2]) - 5,
                                    max(coords[0::2]) + 5, max(coords[1::2]) + 5,
                                    outline="blue", dash=(5, 5), width=2, tags="highlight"
                                )

                        if shape.shape_type in ("ortho_line", "ortho_arrow"):
                            self.draw_ortho_handles(shape)
                            n = len(shape.waypoints)
                            self.status_bar.config(
                                text=f"Selected {shape.shape_type} "
                                     f"({n} waypoint{'s' if n != 1 else ''}) "
                                     f"— drag any point | R to flip routing"
                            )
                        elif shape.shape_type in ("line", "arrow"):
                            self.draw_endpoint_handles(shape)
                            self.status_bar.config(
                                text=f"Selected {shape.shape_type} — drag endpoints to connect")
                        elif shape.shape_type in ["rectangle", "square", "circle", "ellipse", "triangle"]:
                            self.draw_resize_handles(shape)
                            self.status_bar.config(
                                text=f"Selected {shape.shape_type} — drag corners to resize")
                        else:
                            self.status_bar.config(text=f"Selected {shape.shape_type}")
                        return

        self.status_bar.config(text="No shape selected")

    def draw_ortho_handles(self, shape):
        """Draw draggable handles at every point of an ortho line."""
        hs = 6
        all_pts = [[shape.x1, shape.y1]] + (shape.waypoints or []) + [[shape.x2, shape.y2]]
        for i, (px, py) in enumerate(all_pts):
            if i == 0:
                tag, fill, outline = "ortho_start_handle", "green", "darkgreen"
            elif i == len(all_pts) - 1:
                tag, fill, outline = "ortho_end_handle", "red", "darkred"
            else:
                tag, fill, outline = f"ortho_wp_{i - 1}_handle", "#4488FF", "darkblue"
            self.canvas.create_oval(
                px - hs, py - hs, px + hs, py + hs,
                fill=fill, outline=outline, width=2,
                tags=("endpoint_handle", tag)
            )

    def draw_endpoint_handles(self, shape):
        """Draw handles on straight line/arrow endpoints."""
        if shape.shape_type not in ("line", "arrow"):
            return
        hs = 6
        self.canvas.create_oval(shape.x1 - hs, shape.y1 - hs, shape.x1 + hs, shape.y1 + hs,
                                 fill="green", outline="darkgreen", width=2,
                                 tags=("endpoint_handle", "start_handle"))
        self.canvas.create_oval(shape.x2 - hs, shape.y2 - hs, shape.x2 + hs, shape.y2 + hs,
                                 fill="red", outline="darkred", width=2,
                                 tags=("endpoint_handle", "end_handle"))

    def draw_resize_handles(self, shape):
        if shape.shape_type in LINE_TYPES or shape.shape_type == "text":
            return
        hs = 5
        x1, y1, x2, y2 = shape.x1, shape.y1, shape.x2, shape.y2
        if x1 > x2: x1, x2 = x2, x1
        if y1 > y2: y1, y2 = y2, y1
        for hid, (hx, hy) in {'nw': (x1,y1), 'ne': (x2,y1), 'sw': (x1,y2), 'se': (x2,y2)}.items():
            self.canvas.create_rectangle(hx - hs, hy - hs, hx + hs, hy + hs,
                                          fill="white", outline="blue", width=2,
                                          tags=("resize_handle", f"{hid}_handle"))

    # ------------------------------------------------------------------
    # Delete / deselect
    # ------------------------------------------------------------------

    def delete_selected(self):
        if self.canvas_manager.selected_shape:
            self.canvas.delete("highlight")
            self.canvas.delete("endpoint_handle")
            self.canvas.delete("resize_handle")
            self.canvas.delete("label_highlight")
            self.canvas_manager.delete_shape(self.canvas_manager.selected_shape)
            self.resizing_shape = False
            self.resize_handle = None
            self.resize_center = None
            self.editing_label = False
            self.label_shape = None
            self.editing_waypoint = None

    def deselect_all(self):
        if self.ortho_in_progress:
            self._cancel_ortho_drawing()
            self.status_bar.config(text="Drawing cancelled")
            return
        self.canvas_manager.clear_selection()
        self.status_bar.config(text="Deselected")

    def select_all(self):
        self.status_bar.config(text="Select all not yet implemented")

    def check_unsaved_changes(self):
        return self.file_manager.check_unsaved()

    # ------------------------------------------------------------------
    # Grid
    # ------------------------------------------------------------------

    def toggle_grid(self):
        self.grid_enabled = self.grid_enabled_var.get()
        self.draw_grid()
        self.status_bar.config(text=f"Grid {'enabled' if self.grid_enabled else 'disabled'}")

    def toggle_grid_shortcut(self):
        self.grid_enabled_var.set(not self.grid_enabled_var.get())
        self.toggle_grid()

    def toggle_snap(self):
        self.snap_to_grid = self.snap_enabled_var.get()
        self.status_bar.config(text=f"Snap to grid {'enabled' if self.snap_to_grid else 'disabled'}")

    def toggle_snap_shortcut(self):
        self.snap_enabled_var.set(not self.snap_enabled_var.get())
        self.toggle_snap()

    def change_grid_type(self):
        self.grid_type = self.grid_type_var.get()
        if self.grid_enabled:
            self.draw_grid()
        self.status_bar.config(text=f"Grid type: {self.grid_type}")

    def change_grid_spacing(self):
        self.grid_spacing = self.grid_spacing_var.get()
        if self.grid_enabled:
            self.draw_grid()
        self.status_bar.config(text=f"Grid spacing: {self.grid_spacing}px")

    def draw_grid(self):
        self.canvas.delete("grid")
        if not self.grid_enabled:
            return
        w = self.canvas.winfo_width() or 1200
        h = self.canvas.winfo_height() or 800
        sp = self.grid_spacing
        if self.grid_type == "lines":
            for x in range(0, w, sp):
                self.canvas.create_line(x, 0, x, h, fill="#E0E0E0", tags="grid", state='disabled')
            for y in range(0, h, sp):
                self.canvas.create_line(0, y, w, y, fill="#E0E0E0", tags="grid", state='disabled')
        else:
            for x in range(0, w, sp):
                for y in range(0, h, sp):
                    self.canvas.create_oval(x-1, y-1, x+1, y+1,
                                            fill="#B0B0B0", outline="", tags="grid", state='disabled')
        self.canvas.tag_lower("grid")

    def snap_point(self, x, y):
        if not self.snap_to_grid:
            return x, y
        sp = self.grid_spacing
        return round(x / sp) * sp, round(y / sp) * sp

    def on_canvas_resize(self, event):
        new_size = (event.width, event.height)
        if new_size != self.last_canvas_size:
            self.last_canvas_size = new_size
            if self.grid_enabled:
                self.canvas.after_idle(self.draw_grid)

    # ------------------------------------------------------------------
    # Text
    # ------------------------------------------------------------------

    def create_text_at_position(self, x, y):
        dialog = TextInputDialog(self.root, "Add Text", x, y)
        if dialog.result:
            shape = Shape(x1=x, y1=y, x2=x, y2=y,
                          color=self.current_color, width=self.line_width,
                          shape_type="text", text=dialog.result['text'],
                          font_family=dialog.result['font_family'],
                          font_size=dialog.result['font_size'],
                          font_bold=dialog.result['font_bold'],
                          font_italic=dialog.result['font_italic'])
            self.canvas_manager.add_shape(shape)
            self.status_bar.config(text="Text added")

    def edit_text_shape(self, shape):
        dialog = TextInputDialog(self.root, "Edit Text", shape.x1, shape.y1,
                                 initial_text=shape.text, initial_font=shape.font_family,
                                 initial_size=shape.font_size, initial_bold=shape.font_bold,
                                 initial_italic=shape.font_italic)
        if dialog.result:
            shape.text = dialog.result['text']
            shape.font_family = dialog.result['font_family']
            shape.font_size = dialog.result['font_size']
            shape.font_bold = dialog.result['font_bold']
            shape.font_italic = dialog.result['font_italic']
            shape.color = self.current_color
            self.canvas_manager.redraw_shape(shape)
            self.canvas_manager.record_state()
            self.status_bar.config(text="Text updated")

    def add_label_to_selected(self):
        if not self.canvas_manager.selected_shape:
            messagebox.showinfo("No Selection", "Please select a shape first to add a label.")
            return
        shape = self.canvas_manager.selected_shape
        if shape.shape_type == "text":
            messagebox.showinfo("Cannot Label Text", "Text shapes cannot have labels.")
            return
        dialog = LabelInputDialog(self.root, "Add Label to Shape", initial_text=shape.label or "")
        if dialog.result is not None:
            if dialog.result == "":
                if shape.label_canvas_id:
                    self.canvas.delete(shape.label_canvas_id)
                    shape.label_canvas_id = None
                shape.label = None
            else:
                shape.label = dialog.result
                if shape.label_offset_x == 0 and shape.label_offset_y == 0:
                    # Lines: place label above; all other shapes: place below
                    shape.label_offset_y = -20 if shape.shape_type in LINE_TYPES else 20
            self.canvas_manager.redraw_shape(shape)
            self.canvas_manager.record_state()
            self.status_bar.config(text="Label updated")


# ============================================================================
# Dialogs
# ============================================================================

class LabelInputDialog:
    def __init__(self, parent, title, initial_text=""):
        self.result = None
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        self.dialog.geometry("350x150")

        f = ttk.Frame(self.dialog, padding=20)
        f.pack(fill=tk.BOTH, expand=True)
        ttk.Label(f, text="Label Text:").pack(anchor=tk.W, pady=(0, 5))
        self.entry = ttk.Entry(f, width=40)
        self.entry.pack(fill=tk.X, pady=(0, 15))
        self.entry.insert(0, initial_text)
        self.entry.focus()
        self.entry.select_range(0, tk.END)

        bf = ttk.Frame(f)
        bf.pack(fill=tk.X)
        ttk.Button(bf, text="OK", command=self.ok_clicked).pack(side=tk.RIGHT, padx=5)
        ttk.Button(bf, text="Cancel", command=self.cancel_clicked).pack(side=tk.RIGHT)
        ttk.Button(bf, text="Remove Label", command=self.remove_clicked).pack(side=tk.LEFT)
        self.dialog.bind("<Return>", lambda e: self.ok_clicked())
        self.dialog.bind("<Escape>", lambda e: self.cancel_clicked())
        parent.wait_window(self.dialog)

    def ok_clicked(self):
        self.result = self.entry.get().strip()
        self.dialog.destroy()

    def remove_clicked(self):
        self.result = ""
        self.dialog.destroy()

    def cancel_clicked(self):
        self.result = None
        self.dialog.destroy()


class TextInputDialog:
    def __init__(self, parent, title, x, y, initial_text="", initial_font="Arial",
                 initial_size=12, initial_bold=False, initial_italic=False):
        self.result = None
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        self.dialog.geometry("400x300")

        f = ttk.Frame(self.dialog, padding=10)
        f.pack(fill=tk.BOTH, expand=True)
        ttk.Label(f, text="Text:").grid(row=0, column=0, sticky=tk.W, pady=5)

        tf = ttk.Frame(f)
        tf.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        self.text_widget = tk.Text(tf, height=5, width=40, wrap=tk.WORD)
        self.text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.text_widget.insert("1.0", initial_text)
        self.text_widget.focus()
        sb = ttk.Scrollbar(tf, command=self.text_widget.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_widget.config(yscrollcommand=sb.set)

        ttk.Label(f, text="Font:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.font_family = tk.StringVar(value=initial_font)
        ttk.Combobox(f, textvariable=self.font_family, width=15,
                     values=["Arial", "Times New Roman", "Courier New",
                             "Helvetica", "Verdana", "Georgia", "Comic Sans MS"]
                     ).grid(row=2, column=1, sticky=tk.W, pady=5, padx=5)

        ttk.Label(f, text="Size:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.font_size = tk.IntVar(value=initial_size)
        ttk.Spinbox(f, from_=8, to=72, textvariable=self.font_size, width=10
                    ).grid(row=3, column=1, sticky=tk.W, pady=5, padx=5)

        sf = ttk.Frame(f)
        sf.grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=5)
        self.font_bold = tk.BooleanVar(value=initial_bold)
        ttk.Checkbutton(sf, text="Bold", variable=self.font_bold).pack(side=tk.LEFT, padx=5)
        self.font_italic = tk.BooleanVar(value=initial_italic)
        ttk.Checkbutton(sf, text="Italic", variable=self.font_italic).pack(side=tk.LEFT, padx=5)

        bf = ttk.Frame(self.dialog, padding=10)
        bf.pack(fill=tk.X)
        ttk.Button(bf, text="OK", command=self.ok_clicked).pack(side=tk.RIGHT, padx=5)
        ttk.Button(bf, text="Cancel", command=self.cancel_clicked).pack(side=tk.RIGHT)
        self.dialog.bind("<Return>", lambda e: self.ok_clicked())
        self.dialog.bind("<Escape>", lambda e: self.cancel_clicked())
        parent.wait_window(self.dialog)

    def ok_clicked(self):
        text = self.text_widget.get("1.0", "end-1c").strip()
        if text:
            self.result = {'text': text, 'font_family': self.font_family.get(),
                           'font_size': self.font_size.get(), 'font_bold': self.font_bold.get(),
                           'font_italic': self.font_italic.get()}
        self.dialog.destroy()

    def cancel_clicked(self):
        self.result = None
        self.dialog.destroy()
