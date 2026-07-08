# ============================================================================
# FILE: dialogs.py
# ============================================================================
"""
Dialog classes for abDraw (extracted from drawing_app.py, July 2026).

All dialogs are self-contained Tk Toplevels: they set `self.result` (or None
on cancel) and block via wait_window. They have no dependency on the app
object; callers pass in any initial values.
"""
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from canvas_manager import DASH_PATTERNS, DASH_ORDER, DASH_LABELS


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


class SheetSizeDialog:
    """Custom sheet width/height entry (canvas pixel units)."""

    def __init__(self, parent, title, current_w, current_h):
        self.result = None
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        self.dialog.geometry("320x180")

        f = ttk.Frame(self.dialog, padding=20)
        f.pack(fill=tk.BOTH, expand=True)

        ttk.Label(f, text="Width (px):").grid(row=0, column=0, sticky=tk.W, pady=6)
        self.width_var = tk.IntVar(value=current_w)
        ttk.Spinbox(f, from_=200, to=10000, increment=50, width=12,
                   textvariable=self.width_var).grid(row=0, column=1, sticky=tk.W, padx=8)

        ttk.Label(f, text="Height (px):").grid(row=1, column=0, sticky=tk.W, pady=6)
        self.height_var = tk.IntVar(value=current_h)
        ttk.Spinbox(f, from_=200, to=10000, increment=50, width=12,
                   textvariable=self.height_var).grid(row=1, column=1, sticky=tk.W, padx=8)

        ttk.Label(f, text="(1 px ≈ 1/100 inch at default zoom)",
                 font=("Arial", 8), foreground="#666666"
                 ).grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(4, 0))

        bf = ttk.Frame(f)
        bf.grid(row=3, column=0, columnspan=2, sticky=tk.E, pady=(16, 0))
        ttk.Button(bf, text="OK", command=self.ok_clicked).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bf, text="Cancel", command=self.cancel_clicked).pack(side=tk.RIGHT)

        self.dialog.bind("<Return>", lambda e: self.ok_clicked())
        self.dialog.bind("<Escape>", lambda e: self.cancel_clicked())
        parent.wait_window(self.dialog)

    def ok_clicked(self):
        try:
            w = max(200, int(self.width_var.get()))
            h = max(200, int(self.height_var.get()))
            self.result = (w, h)
        except (ValueError, tk.TclError):
            self.result = None
        self.dialog.destroy()

    def cancel_clicked(self):
        self.result = None
        self.dialog.destroy()


class NoteStyleDialog:
    """Choose an annotation line dash pattern + width, with a live preview."""

    def __init__(self, parent, initial_pattern="dashed", initial_width=2):
        self.result = None
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Annotation Line Style")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        self.dialog.resizable(False, False)

        f = ttk.Frame(self.dialog, padding=14)
        f.pack(fill=tk.BOTH, expand=True)

        ttk.Label(f, text="Style:").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.pattern_var = tk.StringVar(
            value=DASH_LABELS.get(initial_pattern, "Dashed"))
        self._label_to_key = {v: k for k, v in DASH_LABELS.items()}
        ttk.Combobox(f, textvariable=self.pattern_var, width=14, state="readonly",
                     values=[DASH_LABELS[k] for k in DASH_ORDER]).grid(
                     row=0, column=1, sticky=tk.W, padx=6)

        ttk.Label(f, text="Width:").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.width_var = tk.IntVar(value=max(1, int(initial_width)))
        ttk.Spinbox(f, from_=1, to=10, width=6, textvariable=self.width_var).grid(
            row=1, column=1, sticky=tk.W, padx=6)

        self.preview = tk.Canvas(f, width=240, height=40, bg="white",
                                 highlightthickness=1, highlightbackground="#bbb")
        self.preview.grid(row=2, column=0, columnspan=2, pady=(10, 0))

        bf = ttk.Frame(f)
        bf.grid(row=3, column=0, columnspan=2, sticky=tk.E, pady=(12, 0))
        ttk.Button(bf, text="OK", command=self.ok_clicked).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bf, text="Cancel", command=self.cancel_clicked).pack(side=tk.RIGHT)

        self.pattern_var.trace_add("write", lambda *_: self._draw_preview())
        self.width_var.trace_add("write", lambda *_: self._draw_preview())
        self._draw_preview()

        self.dialog.bind("<Return>", lambda e: self.ok_clicked())
        self.dialog.bind("<Escape>", lambda e: self.cancel_clicked())
        parent.wait_window(self.dialog)

    def _key(self):
        return self._label_to_key.get(self.pattern_var.get(), "dashed")

    def _draw_preview(self):
        self.preview.delete("all")
        try:
            w = max(1, int(self.width_var.get()))
        except (tk.TclError, ValueError):
            w = 2
        dash = DASH_PATTERNS.get(self._key(), ())
        self.preview.create_line(16, 20, 224, 20, fill="black", width=w,
                                 dash=dash if dash else ())

    def ok_clicked(self):
        try:
            w = max(1, int(self.width_var.get()))
        except (tk.TclError, ValueError):
            w = 2
        self.result = (self._key(), w)
        self.dialog.destroy()

    def cancel_clicked(self):
        self.result = None
        self.dialog.destroy()


class PinRangeDialog:
    """Prompt for a numbered pin range (prefix + start..end, optional zero-pad)."""

    def __init__(self, parent, initial_prefix="", initial_side="Left", sides=None):
        self.result = None
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Add Pin Range")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        self.dialog.resizable(False, False)

        f = ttk.Frame(self.dialog, padding=14)
        f.pack(fill=tk.BOTH, expand=True)

        ttk.Label(f, text="Prefix:").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.prefix_var = tk.StringVar(value=initial_prefix)
        pe = ttk.Entry(f, textvariable=self.prefix_var, width=16)
        pe.grid(row=0, column=1, columnspan=3, sticky=tk.W, padx=4)

        ttk.Label(f, text="Start:").grid(row=1, column=0, sticky=tk.W, pady=3)
        self.start_var = tk.IntVar(value=1)
        ttk.Spinbox(f, from_=0, to=9999, textvariable=self.start_var,
                    width=6).grid(row=1, column=1, sticky=tk.W, padx=4)
        ttk.Label(f, text="End:").grid(row=1, column=2, sticky=tk.W, padx=(10, 0))
        self.end_var = tk.IntVar(value=16)
        ttk.Spinbox(f, from_=0, to=9999, textvariable=self.end_var,
                    width=6).grid(row=1, column=3, sticky=tk.W, padx=4)

        ttk.Label(f, text="Zero-pad width:").grid(row=2, column=0, columnspan=2,
                                                  sticky=tk.W, pady=3)
        self.pad_var = tk.IntVar(value=0)
        ttk.Spinbox(f, from_=0, to=6, textvariable=self.pad_var,
                    width=6).grid(row=2, column=2, sticky=tk.W, padx=4)

        ttk.Label(f, text="Side:").grid(row=3, column=0, sticky=tk.W, pady=3)
        self.side_var = tk.StringVar(value=initial_side)
        ttk.Combobox(f, textvariable=self.side_var, width=8, state="readonly",
                     values=sides or ["Left", "Right", "Top", "Bottom"]
                     ).grid(row=3, column=1, columnspan=2, sticky=tk.W, padx=4)

        self.preview_var = tk.StringVar()
        ttk.Label(f, textvariable=self.preview_var, foreground="#1f6fc2").grid(
            row=4, column=0, columnspan=4, sticky=tk.W, pady=(8, 0))

        bf = ttk.Frame(f)
        bf.grid(row=5, column=0, columnspan=4, sticky=tk.E, pady=(12, 0))
        ttk.Button(bf, text="OK", command=self.ok_clicked).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bf, text="Cancel", command=self.cancel_clicked).pack(side=tk.RIGHT)

        for v in (self.prefix_var, self.start_var, self.end_var, self.pad_var):
            v.trace_add("write", lambda *_: self._update_preview())
        self._update_preview()

        pe.focus_set()
        self.dialog.bind("<Return>", lambda e: self.ok_clicked())
        self.dialog.bind("<Escape>", lambda e: self.cancel_clicked())
        parent.wait_window(self.dialog)

    def _read(self):
        prefix = self.prefix_var.get().strip()
        try:
            start = int(self.start_var.get()); end = int(self.end_var.get())
            pad = max(0, int(self.pad_var.get()))
        except (tk.TclError, ValueError):
            return None
        return prefix, start, end, pad

    def _names(self, limit=None):
        r = self._read()
        if not r:
            return []
        prefix, start, end, pad = r
        step = 1 if end >= start else -1
        names = []
        for n in range(start, end + step, step):
            num = str(abs(n)).zfill(pad) if pad else str(n)
            names.append(f"{prefix}{num}")
            if limit and len(names) >= limit:
                break
        return names

    def _update_preview(self):
        names = self._names()
        if not names:
            self.preview_var.set("")
            return
        shown = self._names(limit=3)
        txt = ", ".join(shown)
        if len(names) > 3:
            txt += f", …, {names[-1]}"
        self.preview_var.set(f"{len(names)} pin(s):  {txt}")

    def ok_clicked(self):
        r = self._read()
        if not r:
            messagebox.showinfo("Add Range", "Enter valid start/end numbers.", parent=self.dialog)
            return
        prefix, start, end, pad = r
        if not prefix:
            messagebox.showinfo("Add Range", "Enter a prefix (e.g. io).", parent=self.dialog)
            return
        if abs(end - start) + 1 > 256:
            messagebox.showinfo("Add Range", "Range too large (max 256 pins).", parent=self.dialog)
            return
        self.result = (prefix, start, end, pad, self.side_var.get())
        self.dialog.destroy()

    def cancel_clicked(self):
        self.result = None
        self.dialog.destroy()


class PortEditorDialog:
    """Add / remove named pins on a block shape."""
    SIDES = [("Left", "L"), ("Right", "R"), ("Top", "T"), ("Bottom", "B")]

    def __init__(self, parent, title, ports):
        self.result = None
        self.ports = [dict(p) for p in ports]
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        self.dialog.geometry("480x430")

        f = ttk.Frame(self.dialog, padding=12)
        f.pack(fill=tk.BOTH, expand=True)

        ttk.Label(f, text="Pins (name — side):").pack(anchor=tk.W)
        self.listbox = tk.Listbox(f, height=10)
        self.listbox.pack(fill=tk.BOTH, expand=True, pady=(4, 8))
        self.listbox.bind("<Double-Button-1>", lambda e: self.rename_port())

        addf = ttk.Frame(f)
        addf.pack(fill=tk.X)
        ttk.Label(addf, text="Name:").pack(side=tk.LEFT)
        self.name_var = tk.StringVar()
        entry = ttk.Entry(addf, textvariable=self.name_var, width=14)
        entry.pack(side=tk.LEFT, padx=4)
        entry.bind("<Return>", lambda e: self.add_port())
        ttk.Label(addf, text="Side:").pack(side=tk.LEFT)
        self.side_var = tk.StringVar(value="Left")
        ttk.Combobox(addf, textvariable=self.side_var, width=8, state="readonly",
                     values=[s[0] for s in self.SIDES]).pack(side=tk.LEFT, padx=4)
        ttk.Button(addf, text="Add", command=self.add_port).pack(side=tk.LEFT, padx=2)
        ttk.Button(addf, text="Add Range…", command=self.add_range).pack(side=tk.LEFT, padx=2)

        editf = ttk.Frame(f)
        editf.pack(fill=tk.X, pady=6)
        ttk.Button(editf, text="Rename", command=self.rename_port).pack(side=tk.LEFT)
        ttk.Button(editf, text="Move Up", command=lambda: self.move_port(-1)).pack(side=tk.LEFT, padx=4)
        ttk.Button(editf, text="Move Down", command=lambda: self.move_port(1)).pack(side=tk.LEFT)
        ttk.Button(editf, text="Remove", command=self.remove_port).pack(side=tk.RIGHT)

        bf = ttk.Frame(f)
        bf.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Button(bf, text="OK", command=self.ok_clicked).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bf, text="Cancel", command=self.cancel_clicked).pack(side=tk.RIGHT)

        self.refresh()
        self.dialog.bind("<Escape>", lambda e: self.cancel_clicked())
        parent.wait_window(self.dialog)

    def _side_code(self, label):
        return dict(self.SIDES).get(label, "L")

    def _side_label(self, code):
        return {c: l for l, c in self.SIDES}.get(code, "Left")

    def refresh(self):
        self.listbox.delete(0, tk.END)
        for p in self.ports:
            self.listbox.insert(tk.END, f"{p['name']}  —  {self._side_label(p.get('side', 'L'))}")

    def add_port(self):
        name = self.name_var.get().strip()
        if not name:
            return
        if any(p['name'] == name for p in self.ports):
            messagebox.showinfo("Duplicate", f"A pin named '{name}' already exists.")
            return
        self.ports.append({'name': name, 'side': self._side_code(self.side_var.get()),
                           'direction': 'inout'})
        self.name_var.set("")
        self.refresh()

    def add_range(self):
        """Bulk-add a numbered sequence of pins, e.g. io1..io16."""
        base = self.name_var.get().strip()
        dlg = PinRangeDialog(self.dialog, initial_prefix=base,
                             initial_side=self.side_var.get(),
                             sides=[s[0] for s in self.SIDES])
        if dlg.result is None:
            return
        prefix, start, end, pad, side_label = dlg.result
        side = self._side_code(side_label)
        step = 1 if end >= start else -1
        existing = {p['name'] for p in self.ports}
        added, skipped = 0, 0
        for n in range(start, end + step, step):
            num = str(abs(n)).zfill(pad) if pad else str(n)
            name = f"{prefix}{num}"
            if name in existing:
                skipped += 1
                continue
            self.ports.append({'name': name, 'side': side, 'direction': 'inout'})
            existing.add(name)
            added += 1
        self.name_var.set("")
        self.refresh()
        if skipped:
            messagebox.showinfo(
                "Add Range",
                f"Added {added} pin(s); skipped {skipped} duplicate name(s).")

    def rename_port(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showinfo("No Selection", "Select a pin to rename.")
            return
        i = sel[0]
        old = self.ports[i]['name']
        new = simpledialog.askstring("Rename Pin", "New pin name:",
                                     initialvalue=old, parent=self.dialog)
        if new is None:
            return
        new = new.strip()
        if not new or new == old:
            return
        if any(j != i and p['name'] == new for j, p in enumerate(self.ports)):
            messagebox.showinfo("Duplicate", f"A pin named '{new}' already exists.")
            return
        self.ports[i]['name'] = new
        self.refresh()
        self.listbox.selection_set(i)

    def move_port(self, delta):
        """Move the selected pin up/down relative to other pins on its SAME edge."""
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showinfo("No Selection", "Select a pin to move.")
            return
        i = sel[0]
        side = self.ports[i].get('side', 'L')
        # Find the nearest pin on the same side in the move direction.
        j = i + delta
        while 0 <= j < len(self.ports):
            if self.ports[j].get('side', 'L') == side:
                break
            j += delta
        if not (0 <= j < len(self.ports)):
            return  # already first/last on this edge
        self.ports[i], self.ports[j] = self.ports[j], self.ports[i]
        self.refresh()
        self.listbox.selection_set(j)

    def remove_port(self):
        sel = self.listbox.curselection()
        if sel:
            del self.ports[sel[0]]
            self.refresh()

    def ok_clicked(self):
        self.result = self.ports
        self.dialog.destroy()

    def cancel_clicked(self):
        self.result = None
        self.dialog.destroy()


class SpecialPinsDialog:
    """Toggle standard optional pins (en/set/rst/clr...) on a primitive.

    Each spec has a FIXED side, so the user only chooses which pins exist;
    placement is automatic. Checking a pin adds it; unchecking removes it.
    """
    SIDE_WORD = {'T': 'top', 'B': 'bottom', 'L': 'left', 'R': 'right'}

    def __init__(self, parent, title, specs, existing_names):
        self.result = None
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        self.dialog.resizable(False, False)

        f = ttk.Frame(self.dialog, padding=14)
        f.pack(fill=tk.BOTH, expand=True)
        ttk.Label(f, text="Enable optional pins:").pack(anchor=tk.W, pady=(0, 8))

        self.vars = {}
        for spec in specs:
            name = spec['name']
            var = tk.BooleanVar(value=name in existing_names)
            self.vars[name] = var
            word = self.SIDE_WORD.get(spec.get('side', 'L'), 'left')
            ttk.Checkbutton(f, text=f"{name}  \u2014  {word} edge",
                            variable=var).pack(anchor=tk.W, pady=2)

        bf = ttk.Frame(f)
        bf.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(bf, text="OK", command=self.ok_clicked).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bf, text="Cancel", command=self.cancel_clicked).pack(side=tk.RIGHT)

        self.dialog.bind("<Escape>", lambda e: self.cancel_clicked())
        self.dialog.bind("<Return>", lambda e: self.ok_clicked())
        parent.wait_window(self.dialog)

    def ok_clicked(self):
        self.result = {name: var.get() for name, var in self.vars.items()}
        self.dialog.destroy()

    def cancel_clicked(self):
        self.result = None
        self.dialog.destroy()


class TextInputDialog:
    def __init__(self, parent, title, x, y, initial_text="", initial_font="Arial",
                 initial_size=12, initial_bold=False, initial_italic=False,
                 initial_align="left"):
        self.result = None
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        self.dialog.geometry("420x350")

        f = ttk.Frame(self.dialog, padding=10)
        f.pack(fill=tk.BOTH, expand=True)
        ttk.Label(f, text="Text  (Enter = new line, Ctrl+Enter = OK):").grid(
            row=0, column=0, columnspan=3, sticky=tk.W, pady=5)

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

        af = ttk.Frame(f)
        af.grid(row=5, column=0, columnspan=3, sticky=tk.W, pady=5)
        ttk.Label(af, text="Align:").pack(side=tk.LEFT, padx=(0, 6))
        self.text_align = tk.StringVar(value=initial_align or "left")
        for _lbl, _val in (("Left", "left"), ("Center", "center"), ("Right", "right")):
            ttk.Radiobutton(af, text=_lbl, value=_val,
                            variable=self.text_align).pack(side=tk.LEFT, padx=4)

        bf = ttk.Frame(self.dialog, padding=10)
        bf.pack(fill=tk.X)
        ttk.Button(bf, text="OK", command=self.ok_clicked).pack(side=tk.RIGHT, padx=5)
        ttk.Button(bf, text="Cancel", command=self.cancel_clicked).pack(side=tk.RIGHT)
        # Plain Enter inserts a newline in the multi-line Text widget; use
        # Ctrl+Enter to accept the dialog. (A dialog-wide <Return> bind would
        # dismiss the dialog on every newline.)
        self.text_widget.bind("<Control-Return>", lambda e: (self.ok_clicked(), "break")[1])
        self.dialog.bind("<Escape>", lambda e: self.cancel_clicked())
        parent.wait_window(self.dialog)

    def ok_clicked(self):
        text = self.text_widget.get("1.0", "end-1c").strip()
        if text:
            self.result = {'text': text, 'font_family': self.font_family.get(),
                           'font_size': self.font_size.get(), 'font_bold': self.font_bold.get(),
                           'font_italic': self.font_italic.get(),
                           'text_align': self.text_align.get()}
        self.dialog.destroy()

    def cancel_clicked(self):
        self.result = None
        self.dialog.destroy()
