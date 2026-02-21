# ============================================================================
# abDraw - Professional Drawing Package
# ============================================================================
# File structure for your project:
#
# abDraw/
#   ├── main.py              (this file - run this)
#   ├── shapes.py            (shape classes and data structures)
#   ├── file_manager.py      (save/load functionality)
#   ├── canvas_manager.py    (canvas operations)
#   └── drawing_app.py       (bulk of drawing package code)
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
