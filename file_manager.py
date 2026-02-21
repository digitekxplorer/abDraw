# ============================================================================
# FILE: file_manager.py
# ============================================================================
"""
File operations for abDraw (save/load/export)
"""
import json
import os
from tkinter import filedialog, messagebox
from PIL import Image, ImageDraw
import tkinter as tk


class FileManager:
    """Handles file operations for drawings"""

    def __init__(self, app):
        self.app = app
        self.current_file = None
        self.modified = False

    def new_drawing(self):
        """Create a new drawing"""
        if not self.check_unsaved():
            return False

        self.app.canvas_manager.clear_all()
        self.current_file = None
        self.modified = False
        self.app.root.title("abDraw - Untitled")
        return True

    def open_drawing(self):
        """Open a drawing file"""
        if not self.check_unsaved():
            return False

        filename = filedialog.askopenfilename(
            title="Open Drawing",
            defaultextension=".abdraw",
            filetypes=[("abDraw files", "*.abdraw"), ("All files", "*.*")]
        )

        if not filename:
            return False

        try:
            with open(filename, 'r') as f:
                data = json.load(f)

            # Clear current drawing
            self.app.canvas_manager.clear_all()

            # Load shapes
            from shapes import Shape
            for shape_data in data.get('shapes', []):
                shape = Shape.from_dict(shape_data)
                self.app.canvas_manager.add_shape(shape, record_undo=False)

            # Rebuild connections
            self.app.canvas_manager.rebuild_connections()

            self.current_file = filename
            self.modified = False
            self.app.root.title(f"abDraw - {os.path.basename(filename)}")
            self.app.status_bar.config(text=f"Opened: {os.path.basename(filename)}")
            return True

        except Exception as e:
            messagebox.showerror("Error", f"Failed to open file:\n{str(e)}")
            return False

    def save_drawing(self):
        """Save the current drawing"""
        if self.current_file:
            return self.save_to_file(self.current_file)
        else:
            return self.save_drawing_as()

    def save_drawing_as(self):
        """Save drawing with a new filename"""
        filename = filedialog.asksaveasfilename(
            title="Save Drawing As",
            defaultextension=".abdraw",
            filetypes=[("abDraw files", "*.abdraw"), ("All files", "*.*")]
        )

        if not filename:
            return False

        return self.save_to_file(filename)

    def save_to_file(self, filename):
        """Save drawing to specified file"""
        try:
            # Prepare data
            data = {
                'version': '1.0',
                'shapes': [shape.to_dict() for shape in self.app.canvas_manager.shapes]
            }

            # Save to file
            with open(filename, 'w') as f:
                json.dump(data, f, indent=2)

            self.current_file = filename
            self.modified = False
            self.app.root.title(f"abDraw - {os.path.basename(filename)}")
            self.app.status_bar.config(text=f"Saved: {os.path.basename(filename)}")
            return True

        except Exception as e:
            messagebox.showerror("Error", f"Failed to save file:\n{str(e)}")
            return False

    def export_png(self):
        """Export drawing as PNG image"""
        filename = filedialog.asksaveasfilename(
            title="Export as PNG",
            defaultextension=".png",
            filetypes=[("PNG files", "*.png"), ("All files", "*.*")]
        )

        if not filename:
            return

        try:
            from PIL import Image, ImageDraw

            # Get canvas dimensions
            width = self.app.canvas.winfo_width()
            height = self.app.canvas.winfo_height()

            # Create white image
            image = Image.new('RGB', (width, height), 'white')
            draw = ImageDraw.Draw(image)

            # Draw grid if enabled
            if self.app.grid_enabled:
                spacing = self.app.grid_spacing
                if self.app.grid_type == "lines":
                    # Draw vertical lines
                    for x in range(0, width, spacing):
                        draw.line([(x, 0), (x, height)], fill='#E0E0E0', width=1)
                    # Draw horizontal lines
                    for y in range(0, height, spacing):
                        draw.line([(0, y), (width, y)], fill='#E0E0E0', width=1)
                else:  # dots
                    for x in range(0, width, spacing):
                        for y in range(0, height, spacing):
                            draw.ellipse([x - 1, y - 1, x + 1, y + 1], fill='#B0B0B0')

            # Draw all shapes
            for shape in self.app.canvas_manager.shapes:
                self.draw_shape_to_image(draw, shape)

            # Save image
            image.save(filename, 'PNG')
            self.app.status_bar.config(text=f"Exported: {os.path.basename(filename)}")

        except ImportError:
            messagebox.showerror("Error",
                                 "PNG export requires the Pillow library.\n"
                                 "Install it with: pip install Pillow")
        except Exception as e:
            messagebox.showerror("Error", f"Export failed:\n{str(e)}")

    def draw_shape_to_image(self, draw, shape):
        """Draw a shape to PIL ImageDraw"""
        try:
            if shape.shape_type == "line":
                draw.line([(shape.x1, shape.y1), (shape.x2, shape.y2)],
                          fill=shape.color, width=shape.width)

            elif shape.shape_type == "arrow":
                # Draw line
                draw.line([(shape.x1, shape.y1), (shape.x2, shape.y2)],
                          fill=shape.color, width=shape.width)
                # Draw arrowhead
                import math
                angle = math.atan2(shape.y2 - shape.y1, shape.x2 - shape.x1)
                arrow_length = 16
                arrow_width = 6

                # Calculate arrowhead points
                x1 = shape.x2 - arrow_length * math.cos(angle - math.pi / 6)
                y1 = shape.y2 - arrow_length * math.sin(angle - math.pi / 6)
                x2 = shape.x2 - arrow_length * math.cos(angle + math.pi / 6)
                y2 = shape.y2 - arrow_length * math.sin(angle + math.pi / 6)

                draw.polygon([(shape.x2, shape.y2), (x1, y1), (x2, y2)],
                             fill=shape.color)

            elif shape.shape_type in ["rectangle", "square"]:
                coords = [shape.x1, shape.y1, shape.x2, shape.y2]
                if shape.fill_color:
                    draw.rectangle(coords, outline=shape.color,
                                   fill=shape.fill_color, width=shape.width)
                else:
                    draw.rectangle(coords, outline=shape.color, width=shape.width)

            elif shape.shape_type in ["circle", "ellipse"]:
                coords = [shape.x1, shape.y1, shape.x2, shape.y2]
                if shape.fill_color:
                    draw.ellipse(coords, outline=shape.color,
                                 fill=shape.fill_color, width=shape.width)
                else:
                    draw.ellipse(coords, outline=shape.color, width=shape.width)

            elif shape.shape_type == "triangle":
                cx = (shape.x1 + shape.x2) / 2
                points = [(cx, shape.y1), (shape.x1, shape.y2), (shape.x2, shape.y2)]
                if shape.fill_color:
                    draw.polygon(points, outline=shape.color, fill=shape.fill_color)
                else:
                    draw.polygon(points, outline=shape.color)
                # Draw outline with proper width
                if shape.width > 1:
                    for i in range(len(points)):
                        p1 = points[i]
                        p2 = points[(i + 1) % len(points)]
                        draw.line([p1, p2], fill=shape.color, width=shape.width)

        except Exception as e:
            print(f"Error drawing shape {shape.shape_type}: {e}")

    def check_unsaved(self):
        """Check for unsaved changes and prompt user"""
        if not self.modified:
            return True

        result = messagebox.askyesnocancel(
            "Unsaved Changes",
            "Do you want to save your changes?"
        )

        if result is None:  # Cancel
            return False
        elif result:  # Yes
            return self.save_drawing()
        else:  # No
            return True

    def mark_modified(self):
        """Mark the drawing as modified"""
        if not self.modified:
            self.modified = True
            title = self.app.root.title()
            if not title.endswith("*"):
                self.app.root.title(title + " *")
