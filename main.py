# ============================================================================
# abDraw - Professional Drawing Package
#
# History
# 02/14/2026 Initial design: comprehensive, top-grade drawing and diagramming
#            application built entirely in Python
# 06/28/2026 Major revision: added multi-page, pin names, net auto-routing,
#            schematic primitives, buses/bit-slice, special pins, and more
# 06/30/2026 - Shape fill: no-fill / pick-a-color, with pin/label text that
#              auto-contrasts the fill (canvas + PNG/PDF export)
#            - Note Arrow: non-electrical diagonal annotation arrow (never
#              binds; excluded from netlist, DRC, junction dots)
#            - Text alignment: left / center / right (canvas + export)
#            - Fix: export now honors dragged net-label & bit-slice positions
# 07/01/2026 - Group selection: marquee-drag to select multiple shapes,
#              move them together (pinned wires stay coherent), and delete
#              them as one undoable action
#            - Fix: resize handles now follow a snapped move on release
#            - Edit Pins: Add Range... bulk-adds numbered pins (io1..io16),
#              optional zero-pad, skips duplicates; wider Edit Pins dialog
#            - Note Line: non-electrical annotation line with a Line Style...
#              picker (Solid / Dashed / Fine / Long / Dotted / Dash-dot + width),
#              patterns render on canvas and in PNG/PDF export
# 07/02/2026 - Refactor: dialog classes extracted to dialogs.py (no behavior
#              change); fixed stale text_widget bind in LabelInputDialog that
#              broke Ctrl+L Add Label
#            - Refactor: mouse handlers dispatch per interaction mode
#              (self.interaction; _drag_*/_release_* methods); one
#              _reset_interaction_state() on tool/sheet switch
#            - Fix: dragged net labels anchor to an arc-length position on
#              the wire (net_label_t) so they no longer jump when the
#              auto-router rebuilds a rerouted wire
# 07/03/2026 - Sheet reordering: ◀ Move / Move ▶ buttons shift the active
#              sheet within the package; the sheet stays active, the title
#              block's "Sheet N of M" updates, order persists on save/load
# 07/08/2026 - Text dialog: plain Enter now inserts a newline (was dismissing
#              the dialog); Ctrl+Enter accepts. Escape still cancels
# 07/08/2026 - Rename connectors: double-click an on/off-page connector, or
#              Edit > Rename Connector..., to change its name (same name =
#              same node); pre-fills current name, undoable
#
# ============================================================================
# File structure for your project:
#
# abDraw/
#   ├── main.py              (this file - run this)
#   ├── shapes.py            (shape classes and data structures)
#   ├── file_manager.py      (save/load functionality)
#   ├── canvas_manager.py    (canvas operations)
#   ├── drawing_app.py       (bulk of drawing package code)
#   └── dialogs.py           (Tk dialog classes)
#
# To use: Save all sections below into separate files as indicated
# ============================================================================

# ============================================================================
# FILE: main.py
# ============================================================================
import tkinter as tk
from tkinter import ttk, messagebox
import sys

# Import our modules (create these files from sections below)
try:
    from drawing_app import DrawingApp
except ImportError:
    print("Please create all required files from the code sections below")
    print("See the file structure at the top of this code")
    sys.exit(1)


def main():
    """Main entry point for abDraw"""
    root = tk.Tk()
    root.title("abDraw - Professional Drawing Package")

    # Set minimum window size
    root.minsize(1000, 600)

    # Create the application
    app = DrawingApp(root)

    # Handle window close
    def on_closing():
        if app.check_unsaved_changes():
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)

    # Start the application
    root.mainloop()


if __name__ == "__main__":
    main()
