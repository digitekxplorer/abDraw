# ============================================================================
# FILE: drawing_app.py
# ============================================================================
"""
Main application class for abDraw
"""
import tkinter as tk
from tkinter import ttk, colorchooser, messagebox, simpledialog
import math
from functools import partial

from shapes import Shape, make_primitive_ports, set_port_grid, STANDARD_PINS
from file_manager import FileManager
from canvas_manager import (CanvasManager, LINE_TYPES,
                            DASH_PATTERNS, DASH_ORDER, DASH_LABELS)
from dialogs import (LabelInputDialog, SheetSizeDialog, NoteStyleDialog,
                     PortEditorDialog, SpecialPinsDialog, TextInputDialog)


# Shape types that can take an interior fill color.
FILLABLE_TYPES = {
    "rectangle", "square", "circle", "ellipse", "triangle",
    "mux", "register", "adder", "connector", "connector_on",
}


# Standard sheet-size presets (canvas pixel units; not DPI-calibrated).
SHEET_SIZE_PRESETS = [
    ("Letter (1100 x 850)",   1100, 850),
    ("Legal (1400 x 850)",    1400, 850),
    ("Tabloid (1700 x 1100)", 1700, 1100),
    ("ANSI B (1700 x 1100)",  1700, 1100),
    ("ANSI C (2200 x 1700)",  2200, 1700),
    ("ANSI D (3400 x 2200)",  3400, 2200),
    ("A4 (1170 x 827)",       1170, 827),
    ("A3 (1654 x 1170)",      1654, 1170),
]


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
        self.annotation_dash = "dashed"   # default Note Line style

        # Grid
        self.grid_enabled = True
        self.grid_type = "dots"
        self.grid_spacing = 20
        self.snap_to_grid = True
        self.last_canvas_size = (0, 0)
        set_port_grid(self.grid_spacing if self.snap_to_grid else 0)

        # Label editing
        self.editing_label = False
        self.label_shape = None

        # Resize state
        self.resizing_shape = False
        self.resize_handle = None
        self.resize_center = None

        # Group (marquee) selection state — Phase A
        self.marquee_start = None   # (x, y) canvas coords, or None
        self.marquee_rect = None    # live rubber-band canvas item id

        # Group move state — Phase B
        self.group_dragging = False
        self.group_anchor = None    # the grouped shape grabbed to start the drag

        # Interaction mode (handler refactor, Phase 1): ONE string naming the
        # in-progress mouse interaction ("move", "resize", "marquee", ...).
        # Stamped on press alongside the legacy flags; on_drag/on_release will
        # be converted to dispatch on it in later phases.
        self.interaction = None

        # Ortho multi-click drawing state
        self.ortho_in_progress = False
        self.ortho_start = None
        self.ortho_waypoints = []

        # Ortho / line waypoint editing state (select tool)
        # Values: None | "start" | "end" | int (waypoint index)
        self.editing_waypoint = None
        self.editing_segment = None   # index of first waypoint of a dragged mid-segment

        # Net / bit-slice label dragging
        self.editing_net_label = None     # Shape whose net label is being moved
        self.editing_slice_label = None   # Shape whose slice label is being moved
        # Default perpendicular distance (px) these labels sit from their
        # wire, used for any label that hasn't been manually dragged.
        self.default_net_label_distance = 9
        self.default_slice_label_distance = 12

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
        export_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Export", menu=export_menu)
        export_menu.add_command(label="Sheet as PNG...",
                                command=self.file_manager.export_png)
        export_menu.add_command(label="All Sheets as PNG...",
                                command=self.file_manager.export_png_package)
        export_menu.add_separator()
        export_menu.add_command(label="Sheet as PDF...",
                                command=self.file_manager.export_pdf_sheet)
        export_menu.add_command(label="Package as PDF (multi-page)...",
                                command=self.file_manager.export_pdf_package)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)

        edit_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        edit_menu.add_command(label="Undo", command=self.canvas_manager.undo, accelerator="Ctrl+Z")
        edit_menu.add_command(label="Redo", command=self.canvas_manager.redo, accelerator="Ctrl+Y")
        edit_menu.add_separator()
        edit_menu.add_command(label="Copy", command=self.canvas_manager.copy_shape, accelerator="Ctrl+C")
        edit_menu.add_command(label="Paste", command=self.canvas_manager.paste_shape, accelerator="Ctrl+V")
        edit_menu.add_command(label="Paste in Place", command=lambda: self.canvas_manager.paste_shape(in_place=True), accelerator="Ctrl+Shift+V")
        edit_menu.add_command(label="Delete", command=self.delete_selected, accelerator="Delete")
        edit_menu.add_separator()
        edit_menu.add_command(label="Add Label to Shape", command=self.add_label_to_selected, accelerator="Ctrl+L")
        edit_menu.add_command(label="Edit Pins...", command=self.edit_ports_of_selected, accelerator="Ctrl+P")
        edit_menu.add_command(label="Special Pins...", command=self.special_pins_of_selected, accelerator="Ctrl+Shift+P")
        edit_menu.add_separator()
        edit_menu.add_command(label="Toggle Bus (wire)", command=self.toggle_bus_of_selected, accelerator="Ctrl+B")
        arrow_menu = tk.Menu(edit_menu, tearoff=0)
        arrow_menu.add_command(label="No Arrowheads", command=lambda: self.set_wire_arrows('none'))
        arrow_menu.add_command(label="One Arrowhead (end)", command=lambda: self.set_wire_arrows('one'))
        arrow_menu.add_command(label="Two Arrowheads (both ends)", command=lambda: self.set_wire_arrows('both'))
        arrow_menu.add_separator()
        arrow_menu.add_command(label="Cycle Arrowheads", command=self.cycle_wire_arrows, accelerator="Ctrl+Shift+A")
        edit_menu.add_cascade(label="Wire Arrowheads", menu=arrow_menu)
        edit_menu.add_command(label="Bit-Slice Label...", command=self.edit_slice_label_of_selected)
        edit_menu.add_command(label="Bit-Slice Label Distance...", command=self.ui_set_slice_label_distance)
        edit_menu.add_command(label="Net Label...", command=self.edit_net_label_of_selected, accelerator="Ctrl+Shift+N")
        edit_menu.add_command(label="Net Label Distance...", command=self.ui_set_net_label_distance)
        edit_menu.add_command(label="Rotate Connector Port", command=self.rotate_connector_of_selected, accelerator="Ctrl+R")
        edit_menu.add_command(label="Rename Connector...", command=self.rename_connector_of_selected)
        edit_menu.add_command(label="Auto-Route Wire", command=self.auto_route_selected)
        edit_menu.add_separator()
        edit_menu.add_command(label="Select All", command=self.select_all, accelerator="Ctrl+A")

        schem_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Schematic", menu=schem_menu)
        schem_menu.add_command(label="Generate Netlist...",
                               command=self.file_manager.export_netlist)
        schem_menu.add_command(label="Validate Schematic",
                               command=self.validate_schematic)

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

        view_menu.add_separator()
        sheet_size_menu = tk.Menu(view_menu, tearoff=0)
        view_menu.add_cascade(label="Sheet Size", menu=sheet_size_menu)
        # A check mark marks the preset matching the ACTIVE sheet's size
        # (or "Custom" when no preset matches). Kept in sync by
        # _sync_sheet_size_check() on every sheet switch / size change.
        self.sheet_size_var = tk.StringVar(value="")
        for label, w, h in SHEET_SIZE_PRESETS:
            sheet_size_menu.add_radiobutton(
                label=label, variable=self.sheet_size_var, value=label,
                command=partial(self.ui_set_sheet_size, w, h))
        sheet_size_menu.add_separator()
        sheet_size_menu.add_radiobutton(
            label="Custom...", variable=self.sheet_size_var, value="__custom__",
            command=self.ui_custom_sheet_size)
        self._sync_sheet_size_check()

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

        self.sheet_bar = ttk.Frame(canvas_frame)
        self.sheet_bar.pack(side=tk.TOP, fill=tk.X)

        # Canvas + scrollbars — the sheet/page can exceed the viewport.
        canvas_container = ttk.Frame(canvas_frame)
        canvas_container.pack(fill=tk.BOTH, expand=True)

        vbar = ttk.Scrollbar(canvas_container, orient=tk.VERTICAL)
        hbar = ttk.Scrollbar(canvas_container, orient=tk.HORIZONTAL)
        self.canvas = tk.Canvas(canvas_container, bg="#B8B8B8", cursor="crosshair",
                                xscrollcommand=hbar.set, yscrollcommand=vbar.set)
        vbar.config(command=self.canvas.yview)
        hbar.config(command=self.canvas.xview)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        canvas_container.grid_rowconfigure(0, weight=1)
        canvas_container.grid_columnconfigure(0, weight=1)

        self.select_tool("select")
        self.update_scrollregion()
        self.draw_page_boundary()
        self.draw_grid()
        self.refresh_sheet_tabs()
        self.canvas.bind("<Configure>", self.on_canvas_resize)
        self.canvas.after_idle(self.canvas_manager.draw_title_block)

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
            ("Note Arrow",  "annotation_arrow", "↗",
             "Annotation arrow — diagonal, non-electrical, never binds to objects"),
            ("Note Line",   "annotation_line", "⇢",
             "Annotation line — dashed, non-electrical, never binds to objects"),
            ("Ortho Line",  "ortho_line",  "⌐",
             "Draw line with 90° turns — left-click to add turns, right-click or Enter to finish, Esc to cancel"),
            ("Ortho Arrow", "ortho_arrow", "⌐→",
             "Draw arrow with 90° turns — left-click to add turns, right-click or Enter to finish, Esc to cancel"),
            ("Rectangle",   "rectangle",   "⬜",  "Draw rectangle"),
            ("Square",      "square",      "◻️",  "Draw square"),
            ("Circle",      "circle",      "⭕",  "Draw circle"),
            ("Ellipse",     "ellipse",     "⬭",   "Draw ellipse"),
            ("Triangle",    "triangle",    "🔺",  "Draw triangle"),
            ("Mux",         "mux",         "◁",   "Draw mux — drag a box, then enter input count"),
            ("Register",    "register",    "⊐",   "Draw register/flip-flop with clock edge"),
            ("Adder",       "adder",       "✚",   "Draw adder block"),
            ("Off-Page",    "connector",   "◯→",  "Off-page connector — click to place, then name it"),
            ("On-Page",     "connector_on","◎",   "On-page connector — same name links nodes on THIS sheet"),
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

        self.fill_btn = tk.Button(toolbar, text="▣", command=self.choose_fill,
                                  width=3, font=("Arial", 16))
        self.fill_btn.pack(side=tk.LEFT, padx=2)
        self._update_fill_btn()
        ToolTip(self.fill_btn, "Fill color (no fill / pick a color) — applies to the selected shape")

        ttk.Label(toolbar, text="Width:").pack(side=tk.LEFT, padx=5)
        self.width_var = tk.IntVar(value=2)
        width_spin = ttk.Spinbox(toolbar, from_=1, to=10, width=5,
                                 textvariable=self.width_var, command=self.update_width)
        width_spin.pack(side=tk.LEFT, padx=2)
        ToolTip(width_spin, "Line width (1-10)")

        self.note_style_btn = tk.Button(toolbar, text="Line Style…",
                                        command=self.choose_note_style)
        self.note_style_btn.pack(side=tk.LEFT, padx=4)
        ToolTip(self.note_style_btn,
                "Annotation line style (solid / dashed patterns) + width — "
                "sets the default and restyles a selected Note Line/Arrow")

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
        self.root.bind("<Control-Shift-V>", lambda e: self.canvas_manager.paste_shape(in_place=True))
        self.root.bind("<Delete>", lambda e: self.delete_selected())
        self.root.bind("<Control-g>", lambda e: self.toggle_grid_shortcut())
        self.root.bind("<Control-h>", lambda e: self.toggle_snap_shortcut())
        self.root.bind("<Control-l>", lambda e: self.add_label_to_selected())
        self.root.bind("<Control-p>", lambda e: self.edit_ports_of_selected())
        self.root.bind("<Control-Shift-P>", lambda e: self.special_pins_of_selected())
        self.root.bind("<Control-Shift-N>", lambda e: self.edit_net_label_of_selected())
        self.root.bind("<Control-b>", lambda e: self.toggle_bus_of_selected())
        self.root.bind("<Control-r>", lambda e: self.rotate_connector_of_selected())
        self.root.bind("<Control-Shift-A>", lambda e: self.cycle_wire_arrows())
        self.root.bind("<Escape>", lambda e: self.deselect_all())
        self.root.bind("<Return>", lambda e: self._finish_ortho_if_active())
        self.root.bind("<r>", lambda e: self._flip_ortho_routing())
        self.root.bind("<R>", lambda e: self._flip_ortho_routing())

    # ------------------------------------------------------------------
    # Tool selection
    # ------------------------------------------------------------------

    def _reset_interaction_state(self):
        """Clear EVERY in-progress mouse-interaction flag and its canvas
        decoration. One authoritative reset, called on tool switch and sheet
        switch, so no drag state can leak across modes."""
        self.interaction = None
        self.editing_label = False
        self.label_shape = None
        self.resizing_shape = False
        self.resize_handle = None
        self.resize_center = None
        self.editing_net_label = None
        self.editing_slice_label = None
        self.editing_segment = None
        self.editing_waypoint = None
        self.group_dragging = False
        self.group_anchor = None
        self.marquee_start = None
        self.marquee_rect = None
        self.canvas_manager.editing_endpoint = None
        for tag in ("label_highlight", "marquee", "snap_indicator"):
            self.canvas.delete(tag)

    def select_tool(self, tool):
        if self.ortho_in_progress:
            self._cancel_ortho_drawing()

        self.current_tool = tool
        self.canvas_manager.clear_selection()
        self._reset_interaction_state()

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

    def choose_note_style(self):
        """Pick the annotation line dash pattern + width. Sets the default for
        new Note Lines and restyles a selected annotation line/arrow."""
        dlg = NoteStyleDialog(self.root, initial_pattern=self.annotation_dash,
                              initial_width=self.line_width)
        if dlg.result is None:
            return
        pattern, width = dlg.result
        self.annotation_dash = pattern
        self.line_width = width
        self.width_var.set(width)
        sel = self.canvas_manager.selected_shape
        if (sel and sel.shape_type in ("line", "arrow")
                and getattr(sel, 'annotation', False)):
            self.canvas_manager.record_state()
            sel.dash_pattern = pattern
            sel.dashed = (pattern != "solid")
            sel.width = width
            self.canvas_manager.redraw_shape(sel)
            self.file_manager.mark_modified()
        self.status_bar.config(
            text=f"Note line style: {DASH_LABELS.get(pattern, pattern)}, width {width}")

    def _update_fill_btn(self):
        """Reflect the current fill on the toolbar swatch."""
        if self.current_fill:
            self.fill_btn.config(bg=self.current_fill, text="▣")
        else:
            self.fill_btn.config(bg="#f0f0f0", text="⊘")  # no-fill

    def choose_fill(self):
        """Pop a small menu: No Fill or pick a color. Applies to the
        selected fillable shape (if any) and becomes the default for new
        shapes."""
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="No Fill", command=lambda: self.set_fill(""))
        menu.add_command(label="Choose Color…", command=self._pick_fill_color)
        try:
            x = self.fill_btn.winfo_rootx()
            y = self.fill_btn.winfo_rooty() + self.fill_btn.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _pick_fill_color(self):
        init = self.current_fill or "#ffffff"
        color = colorchooser.askcolor(initialcolor=init, title="Fill Color")[1]
        if color:
            self.set_fill(color)

    def set_fill(self, color):
        """Set the active fill ("" = no fill) and apply it to the selected
        fillable shape, if one is selected."""
        self.current_fill = color or ""
        self._update_fill_btn()
        sel = self.canvas_manager.selected_shape
        if sel and sel.shape_type in FILLABLE_TYPES:
            self.canvas_manager.record_state()
            sel.fill_color = color or None
            self.canvas_manager.redraw_shape(sel)
            self.status_bar.config(
                text=("Fill: none" if not color else f"Fill: {color}"))

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
        connected = self._auto_connect_endpoints(shape)
        if not connected:
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
            x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
            if self.snap_to_grid:
                x, y = self.snap_point(x, y)
            self._update_ortho_preview(x, y)

    def on_right_click(self, event):
        """Right-click: finalize an in-progress ortho line at the cursor position."""
        if self.ortho_in_progress:
            x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
            if self.snap_to_grid:
                x, y = self.snap_point(x, y)
            self._finalize_ortho_line(x, y)

    def on_press(self, event):
        # Convert viewport pixels to canvas coords so hit-testing and
        # placement stay correct when the sheet is scrolled.
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

        # --- Ortho click-to-place drawing ---
        if self.current_tool in ("ortho_line", "ortho_arrow"):
            if self.snap_to_grid:
                x, y = self.snap_point(x, y)
            if not self.ortho_in_progress:
                # First click — set start point
                self.ortho_in_progress = True
                self.interaction = "ortho"
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
            # 0. Group move — if a marquee group exists and the press lands on
            #    one of its members, drag the whole group (Phase B).
            if self.canvas_manager.selected_shapes:
                anchor = self._group_shape_at(x, y)
                if anchor is not None:
                    self.group_dragging = True
                    self.interaction = "group_move"
                    self.group_anchor = anchor
                    self.canvas_manager.drag_data = {
                        "x": x, "y": y, "start_x": x, "start_y": y}
                    n = len(self.canvas_manager.selected_shapes)
                    self.status_bar.config(text=f"Moving group of {n} — drag to reposition")
                    return
                # Pressed outside the group — drop it and fall through to normal
                # single selection / marquee behavior.
                self.canvas_manager.clear_group_selection()

            # 1. Resize handle?
            items = self.canvas.find_overlapping(x - 3, y - 3, x + 3, y + 3)
            for item in reversed(items):
                tags = self.canvas.gettags(item)
                if "resize_handle" in tags:
                    for tag in tags:
                        if tag.endswith("_handle") and tag != "resize_handle":
                            self.resizing_shape = True
                            self.interaction = "resize"
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
                            self.interaction = "label"
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

            # 2.5. Net / bit-slice label? (wire decorations, wider hit box —
            # small italic/9pt text is easy to miss otherwise)
            deco_items = self.canvas.find_overlapping(x - 8, y - 8, x + 8, y + 8)
            for item in reversed(deco_items):
                tags = self.canvas.gettags(item)
                for t in tags:
                    if t.startswith("netlabel_"):
                        sid = self._tag_shape_id(t, "netlabel_")
                        shape = self._shape_by_id(sid)
                        if shape:
                            dx, dy = self.canvas_manager.net_label_offset(shape)
                            shape.net_label_dx, shape.net_label_dy = dx, dy
                            self.editing_net_label = shape
                            self.interaction = "net_label"
                            self.canvas_manager.drag_data = {"x": x, "y": y}
                            self.status_bar.config(
                                text=f"Moving net label '{shape.net_name}' — drag to reposition")
                            return
                    if t.startswith("slicelabel_"):
                        sid = self._tag_shape_id(t, "slicelabel_")
                        shape = self._shape_by_id(sid)
                        if shape:
                            dx, dy = self.canvas_manager.slice_label_offset(shape)
                            shape.slice_label_dx, shape.slice_label_dy = dx, dy
                            self.editing_slice_label = shape
                            self.interaction = "slice_label"
                            self.canvas_manager.drag_data = {"x": x, "y": y}
                            self.status_bar.config(
                                text=f"Moving slice label '{shape.slice_label}' — drag to reposition")
                            return

            # 3. Ortho waypoint handle?
            for item in items:
                tags = self.canvas.gettags(item)
                for tag in tags:
                    if tag == "ortho_start_handle":
                        self.editing_waypoint = "start"
                        self.interaction = "waypoint"
                        self.canvas_manager.drag_data = {"x": x, "y": y}
                        self.status_bar.config(text="Dragging start point")
                        return
                    elif tag == "ortho_end_handle":
                        self.editing_waypoint = "end"
                        self.interaction = "waypoint"
                        self.canvas_manager.drag_data = {"x": x, "y": y}
                        self.status_bar.config(text="Dragging end point")
                        return
                    elif tag.startswith("ortho_seg_") and tag.endswith("_handle"):
                        try:
                            self.editing_segment = int(tag[10:-7])
                            self.interaction = "segment"
                            self.canvas_manager.drag_data = {"x": x, "y": y}
                            self.status_bar.config(text="Sliding segment")
                            return
                        except ValueError:
                            pass
                    elif tag.startswith("ortho_wp_") and tag.endswith("_handle"):
                        try:
                            idx = int(tag[9:-7])
                            self.editing_waypoint = idx
                            self.interaction = "waypoint"
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
                    self.interaction = "endpoint"
                    self.canvas_manager.drag_data = {"x": x, "y": y}
                    self.status_bar.config(text="Editing start point — drag to connect")
                    return
                elif "end_handle" in tags:
                    self.canvas_manager.editing_endpoint = "end"
                    self.interaction = "endpoint"
                    self.canvas_manager.drag_data = {"x": x, "y": y}
                    self.status_bar.config(text="Editing end point — drag to connect")
                    return

            # 5. Regular shape selection
            self.handle_selection(x, y)
            if self.canvas_manager.selected_shape:
                self.interaction = "move"
                self.canvas_manager.drag_data = {"x": x, "y": y, "start_x": x, "start_y": y}
            else:
                # Empty canvas — begin a rubber-band marquee (group select).
                self.interaction = "marquee"
                self.marquee_start = (x, y)
                self.marquee_rect = None
        else:
            self.interaction = "draw"
            self.canvas_manager.drag_data = {"x": x, "y": y}

    @staticmethod
    def _tag_shape_id(tag, prefix):
        try:
            return int(tag[len(prefix):])
        except ValueError:
            return None

    def _shape_by_id(self, shape_id):
        if shape_id is None:
            return None
        return next((s for s in self.canvas_manager.shapes if s.shape_id == shape_id), None)

    def on_drag(self, event):
        # Convert viewport pixels to canvas coords so hit-testing and
        # placement stay correct when the sheet is scrolled.
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

        # Rubber-band marquee selection (started on empty canvas, select tool)
        if self.marquee_start is not None:
            self._update_marquee(x, y)
            return

        # Group move (Phase B)
        if self.group_dragging and self.canvas_manager.selected_shapes:
            self._drag_group_move(x, y)
            return

        # Ortho preview during drag (button held after placing a point)
        if self.ortho_in_progress:
            draw_x, draw_y = (self.snap_point(x, y) if self.snap_to_grid else (x, y))
            self._update_ortho_preview(draw_x, draw_y)
            return

        if self.current_tool == "select":
            # Handler-refactor Phase 2: dispatch on the interaction mode
            # stamped in on_press. Each handler keeps its own legacy-flag
            # guard, so a flag cleared mid-gesture (e.g. by a double-click)
            # still no-ops exactly as the old if-ladder did.
            if self.interaction:
                handler = getattr(self, "_drag_" + self.interaction, None)
                if handler:
                    handler(x, y)
            return

        # Preview for regular (non-ortho) drawing tools
        self._drag_tool_preview(x, y)

    # ------------------------------------------------------------------
    # Per-mode drag handlers (dispatched from on_drag via self.interaction)
    # ------------------------------------------------------------------

    def _drag_group_move(self, x, y):
        dx = x - self.canvas_manager.drag_data["x"]
        dy = y - self.canvas_manager.drag_data["y"]
        self._translate_group(dx, dy)
        self.canvas_manager.drag_data["x"] = x
        self.canvas_manager.drag_data["y"] = y
        self.file_manager.mark_modified()

    def _drag_net_label(self, x, y):
        shape = self.editing_net_label
        if shape is None:
            return
        dx = x - self.canvas_manager.drag_data["x"]
        dy = y - self.canvas_manager.drag_data["y"]
        shape.net_label_dx = (shape.net_label_dx or 0) + dx
        shape.net_label_dy = (shape.net_label_dy or 0) + dy
        self.canvas_manager.drag_data["x"] = x
        self.canvas_manager.drag_data["y"] = y
        self.canvas_manager.redraw_shape(shape)
        self.file_manager.mark_modified()

    def _drag_slice_label(self, x, y):
        shape = self.editing_slice_label
        if shape is None:
            return
        dx = x - self.canvas_manager.drag_data["x"]
        dy = y - self.canvas_manager.drag_data["y"]
        shape.slice_label_dx = (shape.slice_label_dx or 0) + dx
        shape.slice_label_dy = (shape.slice_label_dy or 0) + dy
        self.canvas_manager.drag_data["x"] = x
        self.canvas_manager.drag_data["y"] = y
        self.canvas_manager.redraw_shape(shape)
        self.file_manager.mark_modified()

    def _drag_resize(self, x, y):
        shape = self.canvas_manager.selected_shape
        if not (self.resizing_shape and shape):
            return
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

    def _drag_label(self, x, y):
        if not (self.editing_label and self.label_shape):
            return
        dx = x - self.canvas_manager.drag_data["x"]
        dy = y - self.canvas_manager.drag_data["y"]
        self.canvas.move(self.label_shape.label_canvas_id, dx, dy)
        self.canvas.move("label_highlight", dx, dy)
        self.label_shape.label_offset_x += dx
        self.label_shape.label_offset_y += dy
        self.canvas_manager.drag_data["x"] = x
        self.canvas_manager.drag_data["y"] = y
        self.file_manager.mark_modified()

    def _drag_segment(self, x, y):
        # Ortho segment slide — move the whole mid-segment as a unit
        shape = self.canvas_manager.selected_shape
        if self.editing_segment is None or not shape:
            return
        i = self.editing_segment
        if 0 <= i < len(shape.waypoints) - 1:
            cx, cy = self.snap_point(x, y) if self.snap_to_grid else (x, y)
            p0, p1 = shape.waypoints[i], shape.waypoints[i + 1]
            horizontal = abs(p1[0] - p0[0]) >= abs(p1[1] - p0[1])
            if horizontal:          # slide vertically
                p0[1] = cy
                p1[1] = cy
            else:                    # slide horizontally
                p0[0] = cx
                p1[0] = cx
            shape.user_routed = True
            self.canvas_manager.redraw_shape(shape)
            self.canvas.delete("endpoint_handle")
            self.draw_ortho_handles(shape)
            self.canvas.delete("highlight")
            all_x = [shape.x1, shape.x2] + [wp[0] for wp in shape.waypoints]
            all_y = [shape.y1, shape.y2] + [wp[1] for wp in shape.waypoints]
            self.canvas.create_rectangle(
                min(all_x) - 5, min(all_y) - 5, max(all_x) + 5, max(all_y) + 5,
                outline="blue", dash=(5, 5), width=2, tags="highlight")
            self.file_manager.mark_modified()

    def _drag_waypoint(self, x, y):
        shape = self.canvas_manager.selected_shape
        if self.editing_waypoint is None or not shape:
            return

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
            shape.user_routed = True   # explicit manual edit wins

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

    def _drag_endpoint(self, x, y):
        if not (self.canvas_manager.editing_endpoint and self.canvas_manager.selected_shape):
            return
        _sel = self.canvas_manager.selected_shape
        if getattr(_sel, 'annotation', False):
            # Annotation arrows are free: grid snap only, never bind.
            snap_x, snap_y = (self.snap_point(x, y) if self.snap_to_grid else (x, y))
            snap_shape = None
        else:
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

    def _drag_move(self, x, y):
        if (not self.canvas_manager.selected_shape
                or self.canvas_manager.editing_endpoint
                or self.resizing_shape
                or self.editing_waypoint is not None):
            return
        dx = x - self.canvas_manager.drag_data["x"]
        dy = y - self.canvas_manager.drag_data["y"]
        shape = self.canvas_manager.selected_shape
        self.canvas.move(shape.canvas_id, dx, dy)
        self.canvas.move("highlight", dx, dy)
        self.canvas.move("endpoint_handle", dx, dy)
        self.canvas.move("resize_handle", dx, dy)
        self.canvas.move(f"ports_{shape.shape_id}", dx, dy)
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

    def _drag_tool_preview(self, x, y):
        draw_x, draw_y = (self.snap_point(x, y) if self.snap_to_grid else (x, y))
        if self.canvas_manager.temp_shape:
            self.canvas.delete(self.canvas_manager.temp_shape)
        self.canvas_manager.temp_shape = self.draw_preview(
            self.canvas_manager.drag_data["x"],
            self.canvas_manager.drag_data["y"],
            draw_x, draw_y
        )

    def on_release(self, event):
        # Convert viewport pixels to canvas coords so hit-testing and
        # placement stay correct when the sheet is scrolled.
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

        # Handler-refactor Phase 3: capture the mode stamped in on_press,
        # then dispatch. Each _release_* handler keeps its legacy-flag guard.
        mode = self.interaction
        self.interaction = None

        # Finish a rubber-band marquee selection.
        if self.marquee_start is not None:
            self._finish_marquee(x, y)
            return

        # Finish a group move (Phase B).
        if self.group_dragging:
            self._release_group_move(x, y)
            return

        # Ortho lines finalize via right-click or Enter — ignore release
        if self.current_tool in ("ortho_line", "ortho_arrow") and self.ortho_in_progress:
            return

        if self.current_tool == "select":
            if mode:
                handler = getattr(self, "_release_" + mode, None)
                if handler:
                    handler(x, y)
            return

        if self.snap_to_grid:
            x, y = self.snap_point(x, y)
        self._release_draw(x, y)

    # ------------------------------------------------------------------
    # Per-mode release handlers (dispatched from on_release)
    # ------------------------------------------------------------------

    def _release_group_move(self, x, y):
        self.group_dragging = False
        sel = self.canvas_manager.selected_shapes
        start_x = self.canvas_manager.drag_data.get("start_x", x)
        start_y = self.canvas_manager.drag_data.get("start_y", y)
        if (abs(x - start_x) > 2 or abs(y - start_y) > 2) and sel:
            # Snap the whole group so the grabbed shape lands on the grid,
            # preserving every shape's relative position.
            if self.snap_to_grid and self.group_anchor is not None:
                sx, sy = self.snap_point(self.group_anchor.x1, self.group_anchor.y1)
                sdx, sdy = sx - self.group_anchor.x1, sy - self.group_anchor.y1
                if abs(sdx) > 0.1 or abs(sdy) > 0.1:
                    self._translate_group(sdx, sdy)
            self.canvas_manager.record_state()
            n = len(sel)
            self.status_bar.config(
                text=f"Moved {n} object{'s' if n != 1 else ''} (group)")
        self.group_anchor = None

    def _release_net_label(self, x, y):
        if self.editing_net_label is None:
            return
        shape = self.editing_net_label
        self.editing_net_label = None
        # Re-anchor the label to the wire point nearest to where the
        # user dropped it (arc-length fraction), so it stays put when
        # the auto-router later rebuilds the wire.
        base = self.canvas_manager.net_label_base_point(shape)
        if base is not None:
            lx = base[0] + (shape.net_label_dx or 0)
            ly = base[1] + (shape.net_label_dy or 0)
            poly = self.canvas_manager.wire_polyline(shape)
            if len(poly) >= 2:
                t = self.canvas_manager.project_to_polyline(poly, lx, ly)
                ax, ay, _ = self.canvas_manager.polyline_point_at(poly, t)
                shape.net_label_t = t
                shape.net_label_dx = lx - ax
                shape.net_label_dy = ly - ay
        self.canvas_manager.record_state()
        self.status_bar.config(text="Net label moved")

    def _release_slice_label(self, x, y):
        if self.editing_slice_label is None:
            return
        self.editing_slice_label = None
        self.canvas_manager.record_state()
        self.status_bar.config(text="Slice label moved")

    def _release_resize(self, x, y):
        if not self.resizing_shape:
            return
        shape = self.canvas_manager.selected_shape
        self.resizing_shape = False
        self.resize_handle = None
        self.resize_center = None
        if shape:
            # Pin anchors moved with the resized bounds; wires bound to this
            # shape's pins were left at their pre-resize position throughout
            # the drag (only redraw_shape ran on every tick) — snap them onto
            # the shape's new pin positions now.
            self.canvas_manager.update_connected_lines(shape)
        self.canvas_manager.record_state()
        self.status_bar.config(text="Shape resized")

    def _release_label(self, x, y):
        if not self.editing_label:
            return
        self.canvas.delete("label_highlight")
        self.editing_label = False
        self.canvas_manager.record_state()
        self.label_shape = None
        self.status_bar.config(text="Label repositioned")

    def _release_segment(self, x, y):
        if self.editing_segment is None:
            return
        self.editing_segment = None
        self.canvas_manager.record_state()
        self.status_bar.config(text="Segment moved")

    def _release_waypoint(self, x, y):
        if self.editing_waypoint is None:
            return
        shape = self.canvas_manager.selected_shape
        if self.editing_waypoint in ("start", "end") and shape:
            # Check for shape snap and update connections
            ex = shape.x1 if self.editing_waypoint == "start" else shape.x2
            ey = shape.y1 if self.editing_waypoint == "start" else shape.y2
            _, _, snap_shape = self.canvas_manager.get_snap_point(ex, ey, shape)
            if snap_shape:
                shape.connections = [c for c in shape.connections
                                     if c.get('endpoint') != self.editing_waypoint]
                port_name = self.canvas_manager.last_snap_port
                shape.connections.append({
                    'target_id': snap_shape.shape_id,
                    'endpoint': self.editing_waypoint,
                    'port_name': port_name
                })
                self.status_bar.config(
                    text=f"Connected {self.editing_waypoint} to "
                         f"{('pin ' + port_name) if port_name else 'shape'}")
            else:
                shape.connections = [c for c in shape.connections
                                     if c.get('endpoint') != self.editing_waypoint]
                self.status_bar.config(text="Point moved")
            self.canvas.delete("snap_indicator")
        else:
            self.status_bar.config(text="Waypoint moved")
        self.editing_waypoint = None
        self.canvas_manager.record_state()

    def _release_endpoint(self, x, y):
        if not (self.canvas_manager.editing_endpoint and self.canvas_manager.selected_shape):
            return
        _sel = self.canvas_manager.selected_shape
        if getattr(_sel, 'annotation', False):
            # Annotation arrows never bind; drop any stale connection.
            _sel.connections = [c for c in _sel.connections
                                if c.get('endpoint') != self.canvas_manager.editing_endpoint]
            self.canvas.delete("snap_indicator")
            self.canvas_manager.editing_endpoint = None
            self.canvas_manager.record_state()
            self.file_manager.mark_modified()
            return
        snap_x, snap_y, snap_shape = self.canvas_manager.get_snap_point(
            x, y, self.canvas_manager.selected_shape)
        if not snap_shape and self.snap_to_grid:
            snap_x, snap_y = self.snap_point(x, y)
        if snap_shape:
            self.canvas_manager.selected_shape.connections = [
                c for c in self.canvas_manager.selected_shape.connections
                if c.get('endpoint') != self.canvas_manager.editing_endpoint
            ]
            port_name = self.canvas_manager.last_snap_port
            self.canvas_manager.selected_shape.connections.append({
                'target_id': snap_shape.shape_id,
                'endpoint': self.canvas_manager.editing_endpoint,
                'port_name': port_name
            })
            self.status_bar.config(
                text=f"Connected {self.canvas_manager.editing_endpoint} to "
                     f"{('pin ' + port_name) if port_name else 'shape'}")
        else:
            self.canvas_manager.selected_shape.connections = [
                c for c in self.canvas_manager.selected_shape.connections
                if c.get('endpoint') != self.canvas_manager.editing_endpoint
            ]
        self.canvas.delete("snap_indicator")
        self.canvas_manager.editing_endpoint = None
        self.canvas_manager.record_state()
        self.file_manager.mark_modified()

    def _release_move(self, x, y):
        if not self.canvas_manager.selected_shape:
            return
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
                    self.canvas.move("resize_handle", snap_dx, snap_dy)
                    self.canvas.move(f"ports_{shape.shape_id}", snap_dx, snap_dy)
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

    def _release_draw(self, x, y):
        if self.current_tool == "text":
            return
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
            if shape.shape_type in LINE_TYPES:
                self._auto_connect_endpoints(shape)

    def _auto_connect_endpoints(self, line_shape):
        """When a wire is first drawn, bind either endpoint that lands on a
        shape/pin so the connection exists immediately — no follow-up drag."""
        if getattr(line_shape, 'annotation', False):
            return False  # annotation arrows are non-electrical: never bind
        connected = []
        for endpoint in ("start", "end"):
            ex = line_shape.x1 if endpoint == "start" else line_shape.x2
            ey = line_shape.y1 if endpoint == "start" else line_shape.y2
            # Tight tolerance on purpose: this only binds a click that's
            # actually on (or a couple px from) the shape's edge/corner/pin.
            # A wider tolerance (e.g. grid_spacing-based) would swallow a
            # point the user deliberately placed a full grid space away and
            # drag it onto the nearest corner/edge instead.
            snap_x, snap_y, snap_shape = self.canvas_manager.get_snap_point(
                ex, ey, line_shape, max_dist=8)
            if not snap_shape:
                continue
            port_name = self.canvas_manager.last_snap_port
            if endpoint == "start":
                line_shape.x1, line_shape.y1 = snap_x, snap_y
            else:
                line_shape.x2, line_shape.y2 = snap_x, snap_y
            line_shape.connections = [c for c in line_shape.connections
                                      if c.get('endpoint') != endpoint]
            line_shape.connections.append({
                'target_id': snap_shape.shape_id,
                'endpoint': endpoint,
                'port_name': port_name
            })
            connected.append(('pin ' + port_name) if port_name else 'shape')
        if connected:
            # Re-route from a clean slate so the bound path (and its arrowhead)
            # Hand-placed waypoints mean the user routed this wire on purpose:
            # keep them and mark it manual so the auto router won't override.
            if line_shape.shape_type in ("ortho_line", "ortho_arrow"):
                line_shape.manual_route = bool(line_shape.waypoints)
            self.canvas_manager.redraw_shape(line_shape)
            self.canvas_manager.record_state()
            self.file_manager.mark_modified()
            self.status_bar.config(text="Wire connected to " + ", ".join(connected))
        return bool(connected)

    def on_double_click(self, event):
        """Double-click: edit text shapes only.
        Ortho lines are finalized via right-click or Enter — not double-click."""
        if self.current_tool != "select":
            return
        # Convert viewport pixels to canvas coords so hit-testing and
        # placement stay correct when the sheet is scrolled.
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        items = self.canvas.find_overlapping(x - 5, y - 5, x + 5, y + 5)
        for item in reversed(items):
            if "shape" in self.canvas.gettags(item):
                for shape in self.canvas_manager.shapes:
                    if shape.canvas_id == item and shape.shape_type == "text":
                        self.edit_text_shape(shape)
                        return
                    if (shape.canvas_id == item
                            and shape.shape_type in ("connector", "connector_on")):
                        self.rename_connector(shape)
                        return
                    if (shape.canvas_id == item
                            and shape.shape_type in ("ortho_line", "ortho_arrow")):
                        self.insert_waypoint_at(shape, x, y)
                        return

    def insert_waypoint_at(self, shape, x, y):
        """Insert a new draggable bend point into an ortho wire at (x, y).

        The point goes into the segment nearest the click, and the wire is
        flagged user_routed so it honors the manual bend from now on.
        """
        if self.snap_to_grid:
            x, y = self.snap_point(x, y)
        raw = [[shape.x1, shape.y1]] + [list(w) for w in shape.waypoints] + [[shape.x2, shape.y2]]
        # Find the raw segment whose body is closest to the click.
        best_i, best_d = 0, float('inf')
        for i in range(len(raw) - 1):
            d = self._point_segment_dist(x, y, raw[i], raw[i + 1])
            if d < best_d:
                best_d, best_i = d, i
        shape.waypoints.insert(best_i, [x, y])
        shape.user_routed = True
        self.canvas_manager.selected_shape = shape
        self.canvas_manager.redraw_shape(shape)
        self.canvas.delete("endpoint_handle")
        self.draw_ortho_handles(shape)
        self.canvas_manager.update_connected_lines(shape)
        self.canvas_manager.record_state()
        self.status_bar.config(
            text="Waypoint added — drag the blue handle to shape the wire")

    @staticmethod
    def _point_segment_dist(px, py, a, b):
        ax, ay = a
        bx, by = b
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        cx, cy = ax + t * dx, ay + t * dy
        return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def draw_preview(self, x1, y1, x2, y2):
        """Draw preview for regular (single-gesture) drawing tools."""
        if self.current_tool in ("line", "annotation_line"):
            return self.canvas.create_line(x1, y1, x2, y2,
                                           fill=self.current_color, width=self.line_width, dash=(4, 4))
        elif self.current_tool in ("arrow", "annotation_arrow"):
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
        elif self.current_tool == "mux":
            inset = min(20, abs(y2 - y1) * 0.18)
            return self.canvas.create_polygon(
                x1, y1, x1, y2, x2, y2 - inset, x2, y1 + inset,
                outline=self.current_color, fill="", width=self.line_width, dash=(4, 4))
        elif self.current_tool in ("register", "adder"):
            return self.canvas.create_rectangle(x1, y1, x2, y2, outline=self.current_color,
                                                width=self.line_width, dash=(4, 4))
        elif self.current_tool == "triangle":
            cx = (x1 + x2) / 2
            return self.canvas.create_polygon(cx, y1, x1, y2, x2, y2, outline=self.current_color,
                                              fill="", width=self.line_width, dash=(4, 4))
        elif self.current_tool in ("connector", "connector_on"):
            r = 17
            return self.canvas.create_oval(x1 - r, y1 - r, x1 + r, y1 + r,
                                           outline=self.current_color,
                                           width=self.line_width, dash=(4, 4))
        return None

    def create_shape(self, x1, y1, x2, y2):
        """Create a new non-ortho shape from a drag gesture."""
        if self.current_tool in ("connector", "connector_on"):
            r = 17
            on_page = self.current_tool == "connector_on"
            if on_page:
                name = simpledialog.askstring(
                    "On-Page Connector",
                    "Connector name (two on-page connectors sharing a name link "
                    "the same node on THIS sheet):", parent=self.root)
            else:
                name = simpledialog.askstring(
                    "Off-Page Connector",
                    "Connector name (two connectors sharing a name link the same "
                    "node, including across sheets):", parent=self.root)
            if not name or not name.strip():
                return None
            ports = [{'name': 'io', 'side': 'L', 'direction': 'inout',
                      'hide_label': True}]
            return Shape(x1=x1 - r, y1=y1 - r, x2=x1 + r, y2=y1 + r,
                         color=self.current_color, width=self.line_width,
                         shape_type="connector_on" if on_page else "connector",
                         fill_color=self.current_fill or "white",
                         ports=ports, conn_name=name.strip())
        if abs(x2 - x1) < 3 and abs(y2 - y1) < 3:
            return None
        if self.current_tool == "circle":
            r = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
            x1, y1, x2, y2 = x1 - r, y1 - r, x1 + r, y1 + r
        elif self.current_tool == "square":
            size = max(abs(x2 - x1), abs(y2 - y1))
            x2 = x1 + size if x2 > x1 else x1 - size
            y2 = y1 + size if y2 > y1 else y1 - size
        if self.current_tool in ("mux", "register", "adder"):
            nx1, ny1 = min(x1, x2), min(y1, y2)
            nx2, ny2 = max(x1, x2), max(y1, y2)
            params = None
            if self.current_tool == "mux":
                n = simpledialog.askinteger(
                    "Mux Inputs", "Number of data inputs (2–16):",
                    initialvalue=2, minvalue=2, maxvalue=16, parent=self.root)
                if not n:
                    n = 2
                ports = make_primitive_ports("mux", n)
                params = {"inputs": n}
            else:
                ports = make_primitive_ports(self.current_tool)
            return Shape(x1=nx1, y1=ny1, x2=nx2, y2=ny2,
                         color=self.current_color, width=self.line_width,
                         shape_type=self.current_tool, fill_color=self.current_fill,
                         ports=ports, params=params)

        if self.current_tool == "annotation_arrow":
            return Shape(x1=x1, y1=y1, x2=x2, y2=y2,
                         color=self.current_color, width=self.line_width,
                         shape_type="arrow", annotation=True)

        if self.current_tool == "annotation_line":
            pat = self.annotation_dash
            return Shape(x1=x1, y1=y1, x2=x2, y2=y2,
                         color=self.current_color, width=self.line_width,
                         shape_type="line", annotation=True,
                         dashed=(pat != "solid"), dash_pattern=pat)

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
                        self.canvas_manager.highlight_net_group(shape)

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
                        elif shape.shape_type in ["rectangle", "square", "circle", "ellipse",
                                                  "triangle", "mux", "register", "adder"]:
                            self.draw_resize_handles(shape)
                            self.status_bar.config(
                                text=f"Selected {shape.shape_type} — drag corners to resize")
                        elif shape.shape_type == "connector":
                            self.status_bar.config(
                                text=f"Selected off-page connector "
                                     f"'{shape.conn_name}' — same name = same node")
                        elif shape.shape_type == "connector_on":
                            self.status_bar.config(
                                text=f"Selected on-page connector "
                                     f"'{shape.conn_name}' — same name = same node on this sheet")
                        else:
                            self.status_bar.config(text=f"Selected {shape.shape_type}")
                        return

        self.status_bar.config(text="No shape selected")

    # ------------------------------------------------------------------
    # Group (marquee) selection — Phase A: select + highlight only
    # ------------------------------------------------------------------
    def _update_marquee(self, x, y):
        x0, y0 = self.marquee_start
        if self.marquee_rect is not None:
            self.canvas.delete(self.marquee_rect)
        self.marquee_rect = self.canvas.create_rectangle(
            x0, y0, x, y, outline="#2e8b57", dash=(4, 3), width=1,
            fill="", tags="marquee")
        self.status_bar.config(
            text="Selecting region — release to select the shapes it touches")

    def _finish_marquee(self, x, y):
        x0, y0 = self.marquee_start
        self.marquee_start = None
        if self.marquee_rect is not None:
            self.canvas.delete(self.marquee_rect)
            self.marquee_rect = None
        self.canvas.delete("marquee")

        rx1, ry1 = min(x0, x), min(y0, y)
        rx2, ry2 = max(x0, x), max(y0, y)
        # A tiny box is really a click on empty space: clear the selection.
        if (rx2 - rx1) < 3 and (ry2 - ry1) < 3:
            self.canvas_manager.clear_group_selection()
            self.status_bar.config(text="No shape selected")
            return

        picked = []
        for shape in self.canvas_manager.shapes:
            b = self._shape_bounds(shape)
            if b is None:
                continue
            bx1, by1, bx2, by2 = b
            if not (bx1 <= rx2 and bx2 >= rx1 and by1 <= ry2 and by2 >= ry1):
                continue
            # A wire's bbox can span the whole sheet (e.g. a long orthogonal
            # run) while its actual polyline never crosses the marquee box —
            # bbox overlap alone would false-positive it in. Test the real
            # segments for line-like shapes; other shapes keep the bbox test.
            if shape.shape_type in LINE_TYPES or shape.shape_type in ("bus", "ortho_bus"):
                if not self._polyline_intersects_rect(shape, rx1, ry1, rx2, ry2):
                    continue
            picked.append(shape)

        self.canvas_manager.set_group_selection(picked)
        n = len(picked)
        if n:
            self.status_bar.config(
                text=f"Selected {n} object{'s' if n != 1 else ''} (group)")
        else:
            self.status_bar.config(text="No shapes in region")

    @staticmethod
    def _seg_intersects_rect(x1, y1, x2, y2, rx1, ry1, rx2, ry2):
        """True if segment (x1,y1)-(x2,y2) intersects axis-aligned rect."""
        # Either endpoint inside the rect.
        if (rx1 <= x1 <= rx2 and ry1 <= y1 <= ry2) or (rx1 <= x2 <= rx2 and ry1 <= y2 <= ry2):
            return True
        # Liang-Barsky segment-vs-rect clip test.
        dx, dy = x2 - x1, y2 - y1
        p = [-dx, dx, -dy, dy]
        q = [x1 - rx1, rx2 - x1, y1 - ry1, ry2 - y1]
        t0, t1 = 0.0, 1.0
        for pi, qi in zip(p, q):
            if pi == 0:
                if qi < 0:
                    return False
            else:
                tt = qi / pi
                if pi < 0:
                    if tt > t1:
                        return False
                    if tt > t0:
                        t0 = tt
                else:
                    if tt < t0:
                        return False
                    if tt < t1:
                        t1 = tt
        return t0 <= t1

    def _polyline_intersects_rect(self, shape, rx1, ry1, rx2, ry2):
        """True if any segment of a wire's actual routed path (waypoints in
        order, or straight x1,y1-x2,y2 if none) crosses the marquee rect."""
        pts = [(shape.x1, shape.y1)]
        pts.extend((wp[0], wp[1]) for wp in (getattr(shape, 'waypoints', None) or []))
        pts.append((shape.x2, shape.y2))
        for i in range(len(pts) - 1):
            (ax, ay), (bx, by) = pts[i], pts[i + 1]
            if self._seg_intersects_rect(ax, ay, bx, by, rx1, ry1, rx2, ry2):
                return True
        return False

    def _shape_bounds(self, shape):
        """Axis-aligned bounds (x1, y1, x2, y2) of a shape in canvas coords,
        preferring the rendered bbox so text and glyphs are covered."""
        bbox = None
        if getattr(shape, 'canvas_id', None):
            try:
                bbox = self.canvas.bbox(shape.canvas_id)
            except Exception:
                bbox = None
        if bbox:
            return bbox
        xs = [shape.x1, shape.x2]
        ys = [shape.y1, shape.y2]
        for wp in getattr(shape, 'waypoints', None) or []:
            xs.append(wp[0]); ys.append(wp[1])
        return (min(xs), min(ys), max(xs), max(ys))

    def _group_shape_at(self, x, y, pad=4):
        """Return the grouped shape whose bounds contain (x, y), or None.
        A generous bbox test lets the user grab thin wires and hollow shapes."""
        for s in self.canvas_manager.selected_shapes:
            b = self._shape_bounds(s)
            if b and (b[0] - pad) <= x <= (b[2] + pad) and (b[1] - pad) <= y <= (b[3] + pad):
                return s
        return None

    def _translate_group(self, dx, dy):
        """Move every shape in the group selection by (dx, dy), keeping wires
        electrically consistent. A wire endpoint pinned to a block OUTSIDE the
        group stays attached (not translated); endpoints pinned to a block
        INSIDE the group ride along and are re-pinned from the moved block."""
        if dx == 0 and dy == 0:
            return
        cm = self.canvas_manager
        sel = cm.selected_shapes
        sel_ids = {s.shape_id for s in sel}

        for s in sel:
            if s.shape_type in LINE_TYPES:
                ext_pinned = {c.get('endpoint') for c in (s.connections or [])
                              if isinstance(c, dict) and c.get('target_id') not in sel_ids}
                if 'start' not in ext_pinned:
                    s.x1 += dx;  s.y1 += dy
                if 'end' not in ext_pinned:
                    s.x2 += dx;  s.y2 += dy
                for wp in (s.waypoints or []):
                    wp[0] += dx;  wp[1] += dy
            else:
                s.x1 += dx;  s.y1 += dy
                s.x2 += dx;  s.y2 += dy
                for wp in (s.waypoints or []):
                    wp[0] += dx;  wp[1] += dy

        # Re-pin EXTERNAL wires attached to any moved block (a wire outside
        # the group that's pinned to a block we just moved must follow it).
        # In-group wires are excluded via skip_ids: they were already
        # translated as a rigid unit above, so they must NOT be wiped and
        # rerouted from scratch here (that discarded the group's relative
        # layout and let the auto-router restagger from nothing).
        for s in sel:
            if s.shape_type not in LINE_TYPES:
                cm.update_connected_lines(s, skip_ids=sel_ids)

        # Repaint the group and its highlight from the new geometry.
        for s in sel:
            cm.redraw_shape(s)
        cm.redraw_junctions()
        cm.draw_group_highlight()

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
        # Orange square at the midpoint of every segment BETWEEN two waypoints —
        # drag it to slide that whole mid-segment as a unit.
        for k in range(1, len(all_pts) - 2):
            mx = (all_pts[k][0] + all_pts[k + 1][0]) / 2
            my = (all_pts[k][1] + all_pts[k + 1][1]) / 2
            self.canvas.create_rectangle(
                mx - hs, my - hs, mx + hs, my + hs,
                fill="orange", outline="#cc7700", width=2,
                tags=("endpoint_handle", f"ortho_seg_{k - 1}_handle")
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
        # Group delete (Phase C) — remove every marquee-selected shape as one
        # undoable action.
        if self.canvas_manager.selected_shapes:
            self.canvas.delete("group_highlight")
            n = len(self.canvas_manager.selected_shapes)
            self.canvas_manager.delete_shapes(self.canvas_manager.selected_shapes)
            self.group_dragging = False
            self.group_anchor = None
            self.status_bar.config(text=f"Deleted {n} object{'s' if n != 1 else ''} (group)")
            return
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
            self.editing_segment = None
            self.editing_net_label = None
            self.editing_slice_label = None

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

    def _sync_port_grid(self):
        """Keep port anchors aligned to the active snap grid, then redraw
        every shape so existing pins reposition onto the grid."""
        set_port_grid(self.grid_spacing if self.snap_to_grid else 0)
        for shape in self.canvas_manager.shapes:
            self.canvas_manager.redraw_shape(shape)
            self.canvas_manager.update_connected_lines(shape)

    def toggle_snap(self):
        self.snap_to_grid = self.snap_enabled_var.get()
        self._sync_port_grid()
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
        self._sync_port_grid()
        if self.grid_enabled:
            self.draw_grid()
        self.status_bar.config(text=f"Grid spacing: {self.grid_spacing}px")

    def draw_grid(self):
        """Draw grid sized to the ACTIVE SHEET's page dimensions (not the
        viewport), so the grid covers the real page regardless of window
        size or scroll position."""
        self.canvas.delete("grid")
        if not self.grid_enabled:
            return
        sheet = self.canvas_manager.sheets[self.canvas_manager.active_sheet]
        w = sheet.get('width', 1700)
        h = sheet.get('height', 1100)
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
        self.canvas.tag_raise("grid", "page")

    def snap_point(self, x, y):
        if not self.snap_to_grid:
            return x, y
        sp = self.grid_spacing
        return round(x / sp) * sp, round(y / sp) * sp

    def on_canvas_resize(self, event):
        """Page/grid are sized from the sheet, not the viewport, so a window
        resize doesn't need to redraw them — keep the size-change tracker
        only in case future code needs to react to viewport changes."""
        new_size = (event.width, event.height)
        if new_size != self.last_canvas_size:
            self.last_canvas_size = new_size

    # ------------------------------------------------------------------
    # Sheet size (page dimensions)
    # ------------------------------------------------------------------

    def update_scrollregion(self):
        """Sync the canvas scroll region to the active sheet's page size."""
        sheet = self.canvas_manager.sheets[self.canvas_manager.active_sheet]
        w = sheet.get('width', 1700)
        h = sheet.get('height', 1100)
        margin = 60   # let the page breathe a bit past its own edges
        self.canvas.config(scrollregion=(-margin, -margin, w + margin, h + margin))

    def draw_page_boundary(self):
        """Draw the page rectangle (white) on a gray 'pasteboard' background."""
        self.canvas.delete("page")
        sheet = self.canvas_manager.sheets[self.canvas_manager.active_sheet]
        w = sheet.get('width', 1700)
        h = sheet.get('height', 1100)
        self.canvas.config(bg="#B8B8B8")
        self.canvas.create_rectangle(0, 0, w, h, fill="white", outline="#888888",
                                     width=1, tags="page")
        self.canvas.tag_lower("page")

    def _sync_sheet_size_check(self):
        """Mark the Sheet Size menu radio matching the active sheet's
        dimensions. First preset whose w/h match wins (some presets share
        dimensions); "Custom" when nothing matches."""
        if not hasattr(self, 'sheet_size_var'):
            return
        cm = self.canvas_manager
        sheet = cm.sheets[cm.active_sheet]
        w, h = sheet.get('width'), sheet.get('height')
        match = "__custom__"
        for label, pw, ph in SHEET_SIZE_PRESETS:
            if pw == w and ph == h:
                match = label
                break
        self.sheet_size_var.set(match)

    def ui_set_sheet_size(self, width, height):
        i = self.canvas_manager.active_sheet
        self.canvas_manager.set_sheet_size(i, width, height)
        self._sync_sheet_size_check()
        self.status_bar.config(text=f"Sheet size set to {width} x {height}")

    def ui_custom_sheet_size(self):
        sheet = self.canvas_manager.sheets[self.canvas_manager.active_sheet]
        dialog = SheetSizeDialog(self.root, "Custom Sheet Size",
                                 sheet.get('width', 1700), sheet.get('height', 1100))
        if dialog.result:
            w, h = dialog.result
            self.ui_set_sheet_size(w, h)

    # ------------------------------------------------------------------
    # Sheet tabs (drawing package)
    # ------------------------------------------------------------------

    def refresh_sheet_tabs(self):
        if not hasattr(self, 'sheet_bar'):
            return
        for w in self.sheet_bar.winfo_children():
            w.destroy()
        cm = self.canvas_manager
        for i, s in enumerate(cm.sheets):
            active = (i == cm.active_sheet)
            b = tk.Button(self.sheet_bar, text=s['name'],
                          relief=(tk.SUNKEN if active else tk.RAISED),
                          bg=("#cfe3ff" if active else "#f0f0f0"),
                          font=("Arial", 9, "bold" if active else "normal"),
                          command=lambda idx=i: self.ui_switch_sheet(idx))
            b.pack(side=tk.LEFT, padx=1, pady=2)
            b.bind("<Double-Button-1>", lambda e, idx=i: self.ui_rename_sheet(idx))
        ttk.Button(self.sheet_bar, text="＋ Add", width=6,
                   command=self.ui_add_sheet).pack(side=tk.LEFT, padx=(8, 1))
        ttk.Button(self.sheet_bar, text="Rename", width=7,
                   command=lambda: self.ui_rename_sheet(cm.active_sheet)).pack(side=tk.LEFT, padx=1)
        ttk.Button(self.sheet_bar, text="Delete", width=7,
                   command=lambda: self.ui_delete_sheet(cm.active_sheet)).pack(side=tk.LEFT, padx=1)
        ttk.Button(self.sheet_bar, text="◀ Move", width=7,
                   command=lambda: self.ui_move_sheet(-1)).pack(side=tk.LEFT, padx=(8, 1))
        ttk.Button(self.sheet_bar, text="Move ▶", width=7,
                   command=lambda: self.ui_move_sheet(1)).pack(side=tk.LEFT, padx=1)
        ttk.Button(self.sheet_bar, text="Title…", width=7,
                   command=self.ui_edit_package_title).pack(side=tk.RIGHT, padx=1)
        self._sync_sheet_size_check()

    def ui_switch_sheet(self, i):
        self._reset_interaction_state()
        self.canvas_manager.switch_sheet(i)
        self.status_bar.config(
            text=f"Switched to {self.canvas_manager.sheets[i]['name']}")

    def ui_add_sheet(self):
        self.canvas_manager.add_sheet()
        self.status_bar.config(text="Added sheet")

    def ui_move_sheet(self, delta):
        cm = self.canvas_manager
        i = cm.active_sheet
        j = i + delta
        if not (0 <= j < len(cm.sheets)):
            return
        self._reset_interaction_state()
        if cm.move_sheet(i, j):
            self.status_bar.config(
                text=f"Moved '{cm.sheets[j]['name']}' to position {j + 1} of {len(cm.sheets)}")

    def ui_rename_sheet(self, i):
        cur = self.canvas_manager.sheets[i]['name']
        name = simpledialog.askstring("Rename Sheet", "Sheet name:",
                                      initialvalue=cur, parent=self.root)
        if name and name.strip():
            self.canvas_manager.rename_sheet(i, name.strip())

    def ui_delete_sheet(self, i):
        if len(self.canvas_manager.sheets) <= 1:
            messagebox.showinfo("Cannot Delete",
                                "A package must have at least one sheet.")
            return
        name = self.canvas_manager.sheets[i]['name']
        if messagebox.askyesno("Delete Sheet",
                               f"Delete '{name}' and all of its contents?"):
            self.canvas_manager.delete_sheet(i)
            self.status_bar.config(text=f"Deleted {name}")

    def ui_edit_package_title(self):
        cur = self.canvas_manager.package_title
        name = simpledialog.askstring("Package Title", "Drawing package title:",
                                      initialvalue=cur, parent=self.root)
        if name is not None:
            self.canvas_manager.package_title = name.strip() or "Untitled"
            self.canvas_manager.draw_title_block()
            self.file_manager.mark_modified()

    def validate_schematic(self):
        report = self.canvas_manager.build_netlist()
        marked = self.canvas_manager.mark_unconnected_pins()
        nets = report['nets']
        unc = report['unconnected']
        dang = report['dangling']
        lines = [f"Nets found: {len(nets)}",
                 f"Unconnected pins: {len(unc)}  ({marked} ringed on this sheet)",
                 f"Dangling nets (single pin): {len(dang)}"]
        if unc:
            lines.append("")
            lines.append("Unconnected:")
            for (sheet, block, pin) in unc[:12]:
                lines.append(f"   {sheet} / {block} . {pin}")
            if len(unc) > 12:
                lines.append(f"   ... and {len(unc) - 12} more")
        self.status_bar.config(
            text=f"DRC: {len(nets)} nets, {len(unc)} unconnected pins")
        messagebox.showinfo("Schematic Validation", "\n".join(lines))

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
                          font_italic=dialog.result['font_italic'],
                          text_align=dialog.result['text_align'])
            self.canvas_manager.add_shape(shape)
            self.status_bar.config(text="Text added")

    def edit_text_shape(self, shape):
        dialog = TextInputDialog(self.root, "Edit Text", shape.x1, shape.y1,
                                 initial_text=shape.text, initial_font=shape.font_family,
                                 initial_size=shape.font_size, initial_bold=shape.font_bold,
                                 initial_italic=shape.font_italic,
                                 initial_align=getattr(shape, 'text_align', 'left'))
        if dialog.result:
            shape.text = dialog.result['text']
            shape.font_family = dialog.result['font_family']
            shape.font_size = dialog.result['font_size']
            shape.font_bold = dialog.result['font_bold']
            shape.font_italic = dialog.result['font_italic']
            shape.text_align = dialog.result['text_align']
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

    def edit_ports_of_selected(self):
        if not self.canvas_manager.selected_shape:
            messagebox.showinfo("No Selection", "Please select a shape first to edit its pins.")
            return
        shape = self.canvas_manager.selected_shape
        if shape.shape_type in LINE_TYPES or shape.shape_type == "text":
            messagebox.showinfo("Cannot Add Pins",
                                "Pins can only be added to block shapes "
                                "(rectangle, square, circle, ellipse, triangle).")
            return
        dialog = PortEditorDialog(self.root, "Edit Pins", list(shape.ports))
        if dialog.result is not None:
            shape.ports = dialog.result
            # Drop stale port bindings whose pin no longer exists.
            names = {p['name'] for p in shape.ports}
            for s in self.canvas_manager.shapes:
                for c in s.connections:
                    if (c.get('target_id') == shape.shape_id
                            and c.get('port_name') and c['port_name'] not in names):
                        c.pop('port_name', None)
            self.canvas_manager.redraw_shape(shape)
            self.canvas_manager.update_connected_lines(shape)
            self.canvas_manager.record_state()
            self.status_bar.config(text=f"Pins updated ({len(shape.ports)} pin(s))")

    def special_pins_of_selected(self):
        if not self.canvas_manager.selected_shape:
            messagebox.showinfo("No Selection",
                                "Please select a shape first to add special pins.")
            return
        shape = self.canvas_manager.selected_shape
        specs = STANDARD_PINS.get(shape.shape_type)
        if not specs:
            messagebox.showinfo("No Special Pins",
                                f"No special pins are defined for a '{shape.shape_type}'.")
            return
        existing = {p['name'] for p in shape.ports}
        dialog = SpecialPinsDialog(self.root, "Special Pins", specs, existing)
        if dialog.result is None:
            return
        spec_by_name = {s['name']: s for s in specs}
        # Keep all current pins except standard pins the user unchecked.
        new_ports = [p for p in shape.ports
                     if not (p['name'] in dialog.result and not dialog.result[p['name']])]
        have = {p['name'] for p in new_ports}
        # Add checked standard pins that aren't already present.
        for name, checked in dialog.result.items():
            if checked and name not in have:
                new_ports.append(dict(spec_by_name[name]))
        removed = existing - {p['name'] for p in new_ports}
        shape.ports = new_ports
        # Drop stale port bindings whose pin no longer exists.
        if removed:
            for s in self.canvas_manager.shapes:
                for c in s.connections:
                    if (c.get('target_id') == shape.shape_id
                            and c.get('port_name') in removed):
                        c.pop('port_name', None)
        self.canvas_manager.redraw_shape(shape)
        self.canvas_manager.update_connected_lines(shape)
        self.canvas_manager.record_state()
        self.status_bar.config(text=f"Special pins updated ({len(shape.ports)} pin(s))")

    def set_wire_arrows(self, mode):
        """Set arrowhead placement on the selected wire: 'none', 'one', 'both'."""
        shape = self.canvas_manager.selected_shape
        if not shape or shape.shape_type not in LINE_TYPES:
            messagebox.showinfo("Select a Wire",
                                "Select a wire (line/arrow) first to set arrowheads.")
            return
        shape.arrow_ends = mode
        self.canvas_manager.redraw_shape(shape)
        self.canvas_manager.record_state()
        word = {'none': 'no arrowheads',
                'one': 'one arrowhead',
                'both': 'two arrowheads'}[mode]
        self.status_bar.config(text=f"Wire set to {word}")

    def cycle_wire_arrows(self):
        """Cycle the selected wire's arrowheads: none -> one -> both -> none."""
        shape = self.canvas_manager.selected_shape
        if not shape or shape.shape_type not in LINE_TYPES:
            messagebox.showinfo("Select a Wire",
                                "Select a wire (line/arrow) first to set arrowheads.")
            return
        cur = getattr(shape, 'arrow_ends', None)
        if cur is None:  # fall back to the shape-type default
            cur = 'one' if shape.shape_type in ("arrow", "ortho_arrow") else 'none'
        nxt = {'none': 'one', 'one': 'both', 'both': 'none'}[cur]
        self.set_wire_arrows(nxt)

    def toggle_bus_of_selected(self):
        shape = self.canvas_manager.selected_shape
        if not shape or shape.shape_type not in LINE_TYPES:
            messagebox.showinfo("Select a Wire",
                                "Select a wire (line/arrow) first to toggle bus styling.")
            return
        shape.bus = not getattr(shape, "bus", False)
        self.canvas_manager.redraw_shape(shape)
        self.canvas_manager.redraw_junctions()
        self.canvas_manager.record_state()
        self.status_bar.config(text="Bus ON" if shape.bus else "Bus OFF")

    def edit_slice_label_of_selected(self):
        shape = self.canvas_manager.selected_shape
        if not shape or shape.shape_type not in LINE_TYPES:
            messagebox.showinfo("Select a Wire",
                                "Select a wire first to add a bit-slice label.")
            return
        current = getattr(shape, "slice_label", None) or ""
        val = simpledialog.askstring("Bit-Slice Label",
                                     "Bit range (e.g. [7:0]); leave blank to remove:",
                                     initialvalue=current, parent=self.root)
        if val is None:
            return
        shape.slice_label = val.strip() or None
        self.canvas_manager.redraw_shape(shape)
        self.canvas_manager.record_state()
        self.status_bar.config(
            text=f"Slice label: {shape.slice_label}" if shape.slice_label
            else "Slice label removed")

    def ui_set_slice_label_distance(self):
        val = simpledialog.askfloat(
            "Bit-Slice Label Distance",
            "Default distance (px) bit-slice labels sit from their tap point:\n"
            "(only affects labels that haven't been manually dragged)",
            initialvalue=self.default_slice_label_distance,
            minvalue=0, maxvalue=200, parent=self.root)
        if val is None:
            return
        self.default_slice_label_distance = val
        for s in self.canvas_manager.shapes:
            if getattr(s, 'slice_label', None) and s.slice_label_dx is None:
                self.canvas_manager.redraw_shape(s)
        self.status_bar.config(text=f"Default bit-slice label distance: {val}px")

    def rename_connector_of_selected(self):
        shape = self.canvas_manager.selected_shape
        if not shape or shape.shape_type not in ("connector", "connector_on"):
            self.status_bar.config(
                text="Select an on-page or off-page connector first to rename it.")
            return
        self.rename_connector(shape)

    def rename_connector(self, shape):
        """Prompt for a new connector name. Same name = same node
        (across sheets for off-page, on this sheet for on-page)."""
        on_page = shape.shape_type == "connector_on"
        title = "On-Page Connector" if on_page else "Off-Page Connector"
        prompt = ("Connector name (same name = same node on THIS sheet):"
                  if on_page else
                  "Connector name (same name = same node, including across sheets):")
        current = getattr(shape, "conn_name", None) or ""
        name = simpledialog.askstring(title, prompt, initialvalue=current,
                                      parent=self.root)
        if name is None:
            return
        name = name.strip()
        if not name:
            self.status_bar.config(text="Connector name cannot be blank — unchanged.")
            return
        shape.conn_name = name
        self.canvas_manager.redraw_shape(shape)
        self.canvas_manager.record_state()
        self.file_manager.mark_modified()
        kind = "on-page" if on_page else "off-page"
        self.status_bar.config(text=f"Renamed {kind} connector to '{name}'")

    def edit_net_label_of_selected(self):
        shape = self.canvas_manager.selected_shape
        if not shape or shape.shape_type not in LINE_TYPES:
            messagebox.showinfo("Select a Wire",
                                "Select a wire first to set its net label.")
            return
        current = getattr(shape, "net_name", None) or ""
        val = simpledialog.askstring("Net Label",
                                     "Net name (same name = same net); "
                                     "blank to remove:",
                                     initialvalue=current, parent=self.root)
        if val is None:
            return
        shape.net_name = val.strip() or None
        self.canvas_manager.redraw_shape(shape)
        self.canvas_manager.highlight_net_group(shape)
        self.canvas_manager.record_state()
        self.status_bar.config(
            text=f"Net: {shape.net_name}" if shape.net_name else "Net label removed")

    def ui_set_net_label_distance(self):
        val = simpledialog.askfloat(
            "Net Label Distance",
            "Default distance (px) net labels sit from their wire:\n"
            "(only affects labels that haven't been manually dragged)",
            initialvalue=self.default_net_label_distance,
            minvalue=0, maxvalue=200, parent=self.root)
        if val is None:
            return
        self.default_net_label_distance = val
        for s in self.canvas_manager.shapes:
            if getattr(s, 'net_name', None) and s.net_label_dx is None:
                self.canvas_manager.redraw_shape(s)
        self.canvas_manager.redraw_junctions()
        self.status_bar.config(text=f"Default net label distance: {val}px")

    def rotate_connector_of_selected(self):
        shape = self.canvas_manager.selected_shape
        if not shape or shape.shape_type not in ("connector", "connector_on") or not shape.ports:
            messagebox.showinfo("Select a Connector",
                                "Select an off-page connector first to rotate "
                                "its attach side.")
            return
        order = ['L', 'T', 'R', 'B']
        cur = shape.ports[0].get('side', 'L')
        shape.ports[0]['side'] = order[(order.index(cur) + 1) % 4] if cur in order else 'L'
        self.canvas_manager.redraw_shape(shape)
        self.canvas_manager.update_connected_lines(shape)
        self.canvas_manager.record_state()
        self.status_bar.config(
            text=f"Connector attach side: {shape.ports[0]['side']}")

    def auto_route_selected(self):
        shape = self.canvas_manager.selected_shape
        if not shape or shape.shape_type not in ("ortho_line", "ortho_arrow"):
            messagebox.showinfo("Select an Ortho Wire",
                                "Select an orthogonal wire to clear manual "
                                "routing and re-enable auto-routing.")
            return
        shape.manual_route = False
        shape.user_routed = False
        shape.waypoints = []
        self.canvas_manager.update_connected_lines(shape)
        self.canvas_manager.redraw_shape(shape)
        self.canvas_manager.record_state()
        self.status_bar.config(text="Wire re-routed automatically")
