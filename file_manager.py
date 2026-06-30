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
        self._font_cache = {}

    def new_drawing(self):
        """Create a new drawing"""
        if not self.check_unsaved():
            return False

        self.app.canvas_manager.reset_package()
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

            # Load the whole package (v2 multi-sheet, or legacy single-sheet).
            self.app.canvas_manager.load_package(data)

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
            # Prepare data (full multi-sheet package)
            data = self.app.canvas_manager.serialize_package()

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

    # ------------------------------------------------------------------
    # Image / document export (per-sheet and whole-package)
    # ------------------------------------------------------------------

    def export_png(self):
        """Export the ACTIVE sheet as a PNG image."""
        filename = filedialog.asksaveasfilename(
            title="Export Sheet as PNG", defaultextension=".png",
            filetypes=[("PNG files", "*.png"), ("All files", "*.*")])
        if not filename:
            return
        try:
            img = self.render_sheet_image(self.app.canvas_manager.active_sheet)
            img.save(filename, 'PNG')
            self.app.status_bar.config(text=f"Exported: {os.path.basename(filename)}")
        except ImportError:
            self._pillow_error()
        except Exception as e:
            messagebox.showerror("Error", f"Export failed:\n{str(e)}")

    def export_png_package(self):
        """Export every sheet as a numbered PNG into a chosen folder."""
        folder = filedialog.askdirectory(title="Export All Sheets as PNG (choose folder)")
        if not folder:
            return
        cm = self.app.canvas_manager
        try:
            base = self._safe(cm.package_title)
            for i, rec in enumerate(cm.sheets):
                img = self.render_sheet_image(i)
                name = f"{base}_{i + 1:02d}_{self._safe(rec['name'])}.png"
                img.save(os.path.join(folder, name), 'PNG')
            self.app.status_bar.config(
                text=f"Exported {len(cm.sheets)} sheet(s) to {os.path.basename(folder)}")
        except ImportError:
            self._pillow_error()
        except Exception as e:
            messagebox.showerror("Error", f"Export failed:\n{str(e)}")

    def export_pdf_sheet(self):
        """Export the ACTIVE sheet as a single-page PDF."""
        filename = filedialog.asksaveasfilename(
            title="Export Sheet as PDF", defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if not filename:
            return
        try:
            img = self.render_sheet_image(self.app.canvas_manager.active_sheet)
            img.save(filename, 'PDF', resolution=100.0)
            self.app.status_bar.config(text=f"Exported: {os.path.basename(filename)}")
        except ImportError:
            self._pillow_error()
        except Exception as e:
            messagebox.showerror("Error", f"Export failed:\n{str(e)}")

    def export_pdf_package(self):
        """Export the whole package as a single multi-page PDF (one page/sheet)."""
        filename = filedialog.asksaveasfilename(
            title="Export Package as PDF", defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if not filename:
            return
        cm = self.app.canvas_manager
        try:
            pages = [self.render_sheet_image(i) for i in range(len(cm.sheets))]
            if not pages:
                return
            pages[0].save(filename, 'PDF', resolution=100.0,
                          save_all=True, append_images=pages[1:])
            self.app.status_bar.config(
                text=f"Exported {len(pages)}-page PDF: {os.path.basename(filename)}")
        except ImportError:
            self._pillow_error()
        except Exception as e:
            messagebox.showerror("Error", f"Export failed:\n{str(e)}")

    def _pillow_error(self):
        messagebox.showerror("Error",
                             "Image/PDF export requires the Pillow library.\n"
                             "Install it with: pip install Pillow")

    @staticmethod
    def _safe(name):
        keep = "-_. "
        s = "".join(c if (c.isalnum() or c in keep) else "_" for c in (name or "")).strip()
        return s.replace(" ", "_") or "sheet"

    def _font(self, size, bold=False, italic=False):
        from PIL import ImageFont
        key = (size, bold, italic)
        if key in self._font_cache:
            return self._font_cache[key]
        candidates = []
        if bold and italic:
            candidates.append("DejaVuSans-BoldOblique.ttf")
        if bold:
            candidates.append("DejaVuSans-Bold.ttf")
        if italic:
            candidates.append("DejaVuSans-Oblique.ttf")
        candidates += ["DejaVuSans.ttf", "Arial.ttf", "arial.ttf"]
        font = None
        for nm in candidates:
            try:
                font = ImageFont.truetype(nm, size)
                break
            except Exception:
                continue
        if font is None:
            try:
                font = ImageFont.load_default(size)
            except Exception:
                font = ImageFont.load_default()
        self._font_cache[key] = font
        return font

    @staticmethod
    def _anchor(tk_anchor):
        # Map Tk text anchors to Pillow text anchors.
        return {"w": "lm", "e": "rm", "n": "ma", "s": "ms",
                "center": "mm", "nw": "la", "ne": "ra",
                "sw": "ld", "se": "rd"}.get(tk_anchor, "la")

    def _text(self, draw, x, y, s, font, fill, anchor="la", align="left"):
        try:
            draw.text((x, y), str(s), font=font, fill=fill, anchor=anchor, align=align)
        except Exception:
            try:
                draw.text((x, y), str(s), font=font, fill=fill, anchor=anchor)
            except Exception:
                draw.text((x, y), str(s), font=font, fill=fill)

    def render_sheet_image(self, index):
        """Render one sheet to a white PIL image, reusing the canvas_manager
        routing/port/junction geometry. No Ghostscript needed.

        The page is rendered at the SHEET's defined width/height (so PNG/PDF
        export matches what would actually print), expanding only if shape
        content overflows that defined page size.
        """
        from PIL import Image, ImageDraw
        from canvas_manager import LINE_TYPES

        cm = self.app.canvas_manager
        shapes = cm.shapes_for_sheet(index)
        sheet_rec = cm.sheets[index]
        saved = cm.shapes
        cm.shapes = shapes            # geometry methods compute against this sheet
        try:
            # Start from the sheet's defined page size — this is the floor.
            minx = miny = 0
            maxx = sheet_rec.get('width', 1700)
            maxy = sheet_rec.get('height', 1100)

            def acc(px, py):
                nonlocal minx, miny, maxx, maxy
                minx = min(minx, px); miny = min(miny, py)
                maxx = max(maxx, px); maxy = max(maxy, py)

            for s in shapes:
                if s.shape_type in LINE_TYPES:
                    for px, py in cm.wire_polyline(s):
                        acc(px, py)
                else:
                    acc(s.x1, s.y1); acc(s.x2, s.y2)
                    for p in (getattr(s, 'ports', None) or []):
                        ax, ay = s.port_anchor(p['name'])
                        acc(ax, ay)

            margin = 44
            ox = margin - minx
            oy = margin - miny
            page_w = int((maxx - minx) + 2 * margin)
            page_h = int((maxy - miny) + 2 * margin)

            img = Image.new('RGB', (page_w, page_h), 'white')
            draw = ImageDraw.Draw(img)

            def T(px, py):
                return (px + ox, py + oy)

            blocks = [s for s in shapes if s.shape_type not in LINE_TYPES]
            wires = [s for s in shapes if s.shape_type in LINE_TYPES]

            for s in blocks:
                self._img_block(draw, s, T)
            for s in wires:
                self._img_wire(draw, cm, s, T)
            for pt in cm.compute_junctions(shapes):
                x, y = T(pt[0], pt[1])
                draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill='black', outline='black')
            for s in blocks:
                self._img_ports(draw, s, T)

            self._img_title_block(draw, page_w, page_h, index)
            return img
        finally:
            cm.shapes = saved

    def export_netlist(self):
        """Write the package netlist to a text file."""
        import datetime
        report = self.app.canvas_manager.build_netlist()
        filename = filedialog.asksaveasfilename(
            title="Export Netlist",
            defaultextension=".net",
            filetypes=[("Netlist", "*.net"), ("Text", "*.txt"), ("All files", "*.*")])
        if not filename:
            return
        title = self.app.canvas_manager.package_title
        lines = [f"abDraw Netlist - {title}",
                 f"Generated {datetime.datetime.now().isoformat(timespec='seconds')}",
                 f"Nets: {len(report['nets'])}   "
                 f"Unconnected pins: {len(report['unconnected'])}   "
                 f"Dangling nets: {len(report['dangling'])}", ""]
        for net in report['nets']:
            lines.append(f"NET {net['name']}")
            for (sheet, block, pin) in net['pins']:
                lines.append(f"    {sheet} / {block} . {pin}")
            lines.append("")
        if report['unconnected']:
            lines.append("UNCONNECTED PINS")
            for (sheet, block, pin) in report['unconnected']:
                lines.append(f"    {sheet} / {block} . {pin}")
            lines.append("")
        try:
            with open(filename, 'w') as f:
                f.write("\n".join(lines))
            self.app.status_bar.config(
                text=f"Netlist exported: {os.path.basename(filename)}")
        except Exception as e:
            messagebox.showerror("Error", f"Netlist export failed:\n{str(e)}")

    def _img_block(self, draw, s, T):
        """Draw a block/primitive body (no ports) to the export image."""
        import math
        col = s.color
        fill = s.fill_color or None
        w = max(1, int(s.width))
        if s.shape_type in ("rectangle", "square", "register", "adder"):
            draw.rectangle([T(s.x1, s.y1), T(s.x2, s.y2)], outline=col, fill=fill, width=w)
        elif s.shape_type == "mux":
            inset = min(20, abs(s.y2 - s.y1) * 0.18)
            pts = [T(s.x1, s.y1), T(s.x1, s.y2),
                   T(s.x2, s.y2 - inset), T(s.x2, s.y1 + inset)]
            draw.polygon(pts, outline=col, fill=fill)
            if w > 1:
                draw.line(pts + [pts[0]], fill=col, width=w, joint="curve")
        elif s.shape_type in ("circle", "ellipse"):
            draw.ellipse([T(s.x1, s.y1), T(s.x2, s.y2)], outline=col, fill=fill, width=w)
        elif s.shape_type == "triangle":
            cx = (s.x1 + s.x2) / 2
            pts = [T(cx, s.y1), T(s.x1, s.y2), T(s.x2, s.y2)]
            draw.polygon(pts, outline=col, fill=fill)
            if w > 1:
                draw.line(pts + [pts[0]], fill=col, width=w, joint="curve")
        elif s.shape_type == "connector":
            draw.ellipse([T(s.x1, s.y1), T(s.x2, s.y2)], outline=col,
                         fill=(s.fill_color or "white"), width=max(2, w))
            cx, cy = T((s.x1 + s.x2) / 2, (s.y1 + s.y2) / 2)
            self._text(draw, cx, cy, getattr(s, 'conn_name', None) or "?",
                       self._font(12, bold=True),
                       self.app.canvas_manager.label_color_for(s),
                       self._anchor("center"))
        elif s.shape_type == "connector_on":
            draw.ellipse([T(s.x1, s.y1), T(s.x2, s.y2)], outline=col,
                         fill=(s.fill_color or "white"), width=max(2, w))
            ins = 4
            draw.ellipse([T(s.x1 + ins, s.y1 + ins), T(s.x2 - ins, s.y2 - ins)],
                         outline=col, width=max(1, w - 1))
            cx, cy = T((s.x1 + s.x2) / 2, (s.y1 + s.y2) / 2)
            self._text(draw, cx, cy, getattr(s, 'conn_name', None) or "?",
                       self._font(11, bold=True),
                       self.app.canvas_manager.label_color_for(s),
                       self._anchor("center"))
        elif s.shape_type == "text":
            tx, ty = T(s.x1, s.y1)
            size = getattr(s, 'font_size', 12) or 12
            align = getattr(s, 'text_align', 'left') or 'left'
            tk_anch = {"left": "nw", "center": "n", "right": "ne"}.get(align, "nw")
            self._text(draw, tx, ty, getattr(s, 'text', '') or '',
                       self._font(int(size), bold=getattr(s, 'font_bold', False)),
                       col, self._anchor(tk_anch), align=align)
        # Block title label (drawn centered like the canvas label).
        if getattr(s, 'label', None) and s.shape_type not in ("text", "connector", "connector_on"):
            cx, cy = T((s.x1 + s.x2) / 2, (s.y1 + s.y2) / 2)
            self._text(draw, cx, cy, s.label, self._font(11, bold=True),
                       col, self._anchor("center"))

    def _img_ports(self, draw, s, T):
        """Draw pin dots, labels, clock triangles, adder glyph to the image."""
        import math
        lbl_col = self.app.canvas_manager.label_color_for(s)
        for p in (getattr(s, 'ports', None) or []):
            px, py = s.port_anchor(p['name'])
            side = p.get('side', 'L')
            dx, dy = T(px, py)
            draw.ellipse([dx - 2.5, dy - 2.5, dx + 2.5, dy + 2.5],
                         fill=s.color, outline=s.color)
            if not p.get('hide_label'):
                # Match the canvas: push a clk label past its clock triangle.
                off = 12 if p['name'].lower() == 'clk' else (4 if side in ('L', 'R') else 5)
                if side == 'L':
                    lx, ly, anch = px + off, py, "w"
                elif side == 'R':
                    lx, ly, anch = px - off, py, "e"
                elif side == 'T':
                    lx, ly, anch = px, py + off, "n"
                else:
                    lx, ly, anch = px, py - off, "s"
                tx, ty = T(lx, ly)
                self._text(draw, tx, ty, p['name'], self._font(9),
                           lbl_col, self._anchor(anch))
            if p['name'].lower() == 'clk':
                tri = 7
                if side == 'L':
                    pts = [(px, py - tri), (px, py + tri), (px + tri + 2, py)]
                elif side == 'R':
                    pts = [(px, py - tri), (px, py + tri), (px - tri - 2, py)]
                elif side == 'T':
                    pts = [(px - tri, py), (px + tri, py), (px, py + tri + 2)]
                else:
                    pts = [(px - tri, py), (px + tri, py), (px, py - tri - 2)]
                draw.line([T(*pt) for pt in pts] + [T(*pts[0])],
                          fill=s.color, width=max(1, int(s.width) - 1), joint="curve")
        if s.shape_type == "adder":
            cx, cy = T((s.x1 + s.x2) / 2, (s.y1 + s.y2) / 2)
            self._text(draw, cx, cy, "+", self._font(18, bold=True),
                       lbl_col, self._anchor("center"))

    def _img_wire(self, draw, cm, s, T):
        """Draw a wire (straight/ortho), bus width, arrowhead, slice tap, net label."""
        import math
        poly = cm.wire_polyline(s)
        if len(poly) < 2:
            return
        bus = getattr(s, 'bus', False)
        w = max(1, int(s.width + (3 if bus else 0)))
        pts = [T(px, py) for px, py in poly]
        draw.line(pts, fill=s.color, width=w, joint="curve")
        # Arrowheads, honoring an explicit arrow_ends override.
        mode = getattr(s, 'arrow_ends', None)
        if mode is None:
            mode = 'one' if s.shape_type in ("arrow", "ortho_arrow") else 'none'
        size = 20 if bus else 16

        def _arrowhead(tip, base):
            ax, ay = poly[base]
            bx, by = poly[tip]
            ang = math.atan2(by - ay, bx - ax)
            h1 = (bx - size * math.cos(ang - math.pi / 6),
                  by - size * math.sin(ang - math.pi / 6))
            h2 = (bx - size * math.cos(ang + math.pi / 6),
                  by - size * math.sin(ang + math.pi / 6))
            draw.polygon([T(bx, by), T(*h1), T(*h2)], fill=s.color)

        if mode in ("one", "both"):
            _arrowhead(-1, -2)   # arrowhead at the end
        if mode == "both":
            _arrowhead(0, 1)     # arrowhead at the start
        # Bit-slice tap.
        label = getattr(s, 'slice_label', None)
        if label:
            tap = cm.slice_tap_point(s)
            if tap:
                cx, cy, ux, uy = tap
                draw.line([T(cx - 7, cy + 7), T(cx + 7, cy - 7)],
                          fill=s.color, width=max(1, int(s.width)))
                dx, dy = cm.slice_label_offset(s)
                tx, ty = T(cx + dx, cy + dy)
                self._text(draw, tx, ty, label, self._font(9), s.color,
                           self._anchor("center"))
        # Net label — honor the user's drag override (net_label_dx/dy) just as
        # the canvas does, so exports match the on-screen position.
        net = getattr(s, 'net_name', None)
        if net:
            base = cm.net_label_base_point(s)
            if base:
                mx, my, _ = base
                dx, dy = cm.net_label_offset(s)
                tx, ty = T(mx + dx, my + dy)
                self._text(draw, tx, ty, net, self._font(9, italic=True),
                           "#1f6fc2", self._anchor("center"))

    def _img_title_block(self, draw, page_w, page_h, index):
        import datetime
        cm = self.app.canvas_manager
        bw, bh = 330, 92
        x2, y2 = page_w - 8, page_h - 8
        x1, y1 = x2 - bw, y2 - bh
        r1, r2 = y1 + bh * 0.40, y1 + bh * 0.70
        pad = 8
        sheet = cm.sheets[index]
        draw.rectangle([x1, y1, x2, y2], fill="white", outline="black", width=2)
        draw.line([x1, r1, x2, r1], fill="black", width=1)
        draw.line([x1, r2, x2, r2], fill="black", width=1)
        self._text(draw, x1 + pad, y1 + pad, cm.package_title,
                   self._font(11, bold=True), "black", self._anchor("nw"))
        self._text(draw, x2 - pad, y1 + pad, "abDraw",
                   self._font(9), "black", self._anchor("ne"))
        self._text(draw, x1 + pad, r1 + 5, sheet['name'],
                   self._font(9), "black", self._anchor("nw"))
        self._text(draw, x2 - pad, r1 + 5, f"Sheet {index + 1} of {len(cm.sheets)}",
                   self._font(9), "black", self._anchor("ne"))
        self._text(draw, x1 + pad, r2 + 4, datetime.date.today().isoformat(),
                   self._font(8), "#555555", self._anchor("nw"))

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
