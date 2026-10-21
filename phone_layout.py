"""Phone layout editor: plan where the on-screen controls go on the Android app.

Opened from the receiver when you pick Android. On the left is the same Xbox
controller picture as the Mac app; on the right, a phone held sideways. Click
a button on the controller and a box for it appears on the phone. Drag boxes
anywhere on the screen, drag a box's bottom-right corner to resize it, and
right-click one to remove it.

Positions and sizes are stored as fractions of the phone screen (0..1), so the
layout fits any real phone size later. Saved to phone_layout.json next to this file.
This only edits the layout; the phone app doesn't read it yet.
"""

import json
import os
import tkinter as tk

import app_common
from controller_view import ControllerView, FACE_COLORS, TARGET_NAMES

LAYOUT_FILE = os.path.join(app_common.app_dir(), "phone_layout.json")

# Short labels for the boxes on the phone.
BOX_LABELS = {
    "LT": "LT", "RT": "RT", "LB": "LB", "RB": "RB",
    "VIEW": "View", "MENU": "Menu", "GUIDE": "Xbox",
    "LS": "LS", "RS": "RS",
    "DPAD_UP": "Up", "DPAD_DOWN": "Down", "DPAD_LEFT": "Left", "DPAD_RIGHT": "Right",
}
ADDED_COLOR = "#2f4f78"  # controller zone (and box) for a non-face button on the phone

# Box sizes, as fractions of the phone screen (so they scale to any phone).
DEFAULT_W, DEFAULT_H = 0.14, 0.18
MIN_W, MIN_H = 0.06, 0.08    # smaller than this is hard to hit with a thumb
HANDLE = 10                  # resize grip in a box's bottom-right corner, px


def _clamp(value, low, high):
    return min(max(value, low), high)


def load_layout():
    """[{"target", "x", "y", "w", "h"}] from disk, or [].

    x, y are the box's top-left corner and w, h its size, all fractions of
    the screen. Files saved before boxes were resizable have no w/h (and x, y
    were the box's position within the free area); they load at the default
    size in the same place.
    """
    try:
        with open(LAYOUT_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    boxes = []
    for item in data.get("boxes", []) if isinstance(data, dict) else []:
        try:
            target, x, y = item["target"], float(item["x"]), float(item["y"])
            sized = "w" in item and "h" in item
            w = float(item["w"]) if sized else DEFAULT_W
            h = float(item["h"]) if sized else DEFAULT_H
        except (KeyError, TypeError, ValueError):
            continue
        if target not in TARGET_NAMES or any(b["target"] == target for b in boxes):
            continue  # unknown, or a second box for the same button
        w, h = _clamp(w, MIN_W, 1.0), _clamp(h, MIN_H, 1.0)
        if not sized:  # old format: x, y ran 0..1 across the space left over
            x, y = x * (1.0 - w), y * (1.0 - h)
        boxes.append({"target": target, "x": _clamp(x, 0.0, 1.0 - w),
                      "y": _clamp(y, 0.0, 1.0 - h), "w": w, "h": h})
    return boxes


def save_layout(boxes):
    try:
        with open(LAYOUT_FILE, "w", encoding="utf-8") as fh:
            json.dump({"boxes": boxes}, fh, indent=2)
    except OSError:
        pass  # saving is a convenience; the editor still works this session


class PhoneCanvas(tk.Canvas):
    """A landscape phone with draggable, resizable control boxes on its screen."""

    W, H = 520, 260          # whole drawing
    BEZEL = 14               # phone frame around the screen

    def __init__(self, parent, boxes, on_change):
        dark = app_common.is_dark(parent)
        super().__init__(parent, width=self.W, height=self.H, bg=parent.cget("bg"),
                         highlightthickness=0)
        self.on_change = on_change
        self.colors = {
            "frame": "#1c1c1e", "screen": "#2a2a2e" if dark else "#3a3a3e",
            "box": ADDED_COLOR, "box_line": "#8fb4e8", "text": "#f2f2f2",
            "hint": "#9a9a9a",
        }
        # Phone body and screen.
        self._round_rect(2, 2, self.W - 2, self.H - 2, 34, fill=self.colors["frame"], outline="#555")
        b = self.BEZEL
        self.screen = (b + 18, b, self.W - b - 18, self.H - b)  # wider bezel on the short sides
        x0, y0, x1, y1 = self.screen
        self._round_rect(x0, y0, x1, y1, 18, fill=self.colors["screen"], outline="")
        # Camera dot on the left bezel (phone held with the camera to the left).
        self.create_oval(b - 2, self.H / 2 - 5, b + 8, self.H / 2 + 5, fill="#000", outline="#333")
        self.empty_hint = self.create_text(
            (x0 + x1) / 2, (y0 + y1) / 2, fill=self.colors["hint"], font=("Segoe UI", 10),
            text="Click a button on the controller to add it here.\n"
                 "Drag to move, drag the corner to resize, right-click to remove.",
            justify="center")

        self.boxes = {}      # canvas tag -> {"target", "x", "y", "w", "h"}
        self.items = {}      # canvas tag -> (rectangle, label, grip) item ids
        self._drag = None    # ("move" | "resize", tag, grab offset x, grab offset y)
        self._next_id = 0
        for box in boxes:
            self._add(box["target"], box["x"], box["y"], box["w"], box["h"])
        self._update_hint()

    # ----- drawing helpers -----

    def _round_rect(self, x0, y0, x1, y1, r, **kw):
        points = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
                  x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return self.create_polygon(points, smooth=True, **kw)

    def _screen_size(self):
        x0, y0, x1, y1 = self.screen
        return x1 - x0, y1 - y0

    def _rect_px(self, box):
        """A box's fractions -> its corners in canvas px."""
        x0, y0, _x1, _y1 = self.screen
        sw, sh = self._screen_size()
        left, top = x0 + box["x"] * sw, y0 + box["y"] * sh
        return left, top, left + box["w"] * sw, top + box["h"] * sh

    def _redraw(self, tag):
        """Put a box's rectangle, label and grip where its fractions say."""
        rect, label, grip = self.items[tag]
        left, top, right, bottom = self._rect_px(self.boxes[tag])
        self.coords(rect, left, top, right, bottom)
        self.coords(label, (left + right) / 2, (top + bottom) / 2)
        self.coords(grip, right - HANDLE, bottom, right, bottom, right, bottom - HANDLE)
        # Shrink the label with the box so it always fits.
        size = int(_clamp(min(right - left, (bottom - top) * 1.6) / 6, 7, 12))
        self.itemconfig(label, font=("Segoe UI", size, "bold"))

    # ----- boxes -----

    # Where new boxes appear (their centres), in order, so a run of clicks
    # doesn't pile them on top of each other. Cycles once all are used.
    _SPOTS = [(0.5, 0.5), (0.3, 0.5), (0.7, 0.5), (0.5, 0.2), (0.5, 0.8),
              (0.3, 0.2), (0.7, 0.2), (0.3, 0.8), (0.7, 0.8)]

    @staticmethod
    def _corner(spot):
        """Top-left of a default-size box centred on `spot`."""
        return (round(_clamp(spot[0] - DEFAULT_W / 2, 0.0, 1.0 - DEFAULT_W), 3),
                round(_clamp(spot[1] - DEFAULT_H / 2, 0.0, 1.0 - DEFAULT_H), 3))

    def _overlaps(self, x, y):
        """True if a default-size box at (x, y) would cover part of another box."""
        return any(x < b["x"] + b["w"] and b["x"] < x + DEFAULT_W and
                   y < b["y"] + b["h"] and b["y"] < y + DEFAULT_H
                   for b in self.boxes.values())

    def add_box(self, target):
        """New default-size box for `target`, in the first spot not covering
        another box (moved and resized ones included); if the screen is that
        full, the spots are reused in turn."""
        corners = [self._corner(s) for s in self._SPOTS]
        x, y = next((c for c in corners if not self._overlaps(*c)),
                    corners[len(self.boxes) % len(corners)])
        self._add(target, x, y, DEFAULT_W, DEFAULT_H)
        self._update_hint()
        self._changed()

    def _add(self, target, fx, fy, fw, fh):
        tag = f"box{self._next_id}"
        self._next_id += 1
        fill = FACE_COLORS.get(target, self.colors["box"])
        rect = self.create_rectangle(0, 0, 0, 0, fill=fill, outline=self.colors["box_line"],
                                     width=2, tags=(tag, "box"))
        label = self.create_text(0, 0, text=BOX_LABELS.get(target, target),
                                 fill=self.colors["text"], tags=(tag, "box"))
        grip = self.create_polygon(0, 0, 0, 0, 0, 0, fill=self.colors["box_line"],
                                   outline="", tags=(tag, "box"))
        self.boxes[tag] = {"target": target, "x": fx, "y": fy, "w": fw, "h": fh}
        self.items[tag] = (rect, label, grip)
        self._redraw(tag)
        for item in (rect, label):
            self.tag_bind(item, "<ButtonPress-1>", lambda e, t=tag: self._start(t, e, "move"))
            self.tag_bind(item, "<Enter>", lambda _e: self.config(cursor="fleur"))
        self.tag_bind(grip, "<ButtonPress-1>", lambda e, t=tag: self._start(t, e, "resize"))
        self.tag_bind(grip, "<Enter>", lambda _e: self.config(cursor="size_nw_se"))
        self.tag_bind(tag, "<B1-Motion>", self._drag_to)
        self.tag_bind(tag, "<ButtonRelease-1>", self._end_drag)
        self.tag_bind(tag, "<Button-3>", lambda _e, t=tag: self.remove_box(t))
        self.tag_bind(tag, "<Leave>", lambda _e: self.config(cursor=""))

    def remove_box(self, tag):
        self.delete(tag)
        self.boxes.pop(tag, None)
        self.items.pop(tag, None)
        self._update_hint()
        self._changed()

    def clear(self):
        for tag in list(self.boxes):
            self.delete(tag)
        self.boxes.clear()
        self.items.clear()
        self._update_hint()
        self._changed()

    def _start(self, tag, event, mode):
        self.tag_raise(tag)
        left, top, right, bottom = self._rect_px(self.boxes[tag])
        # Remember where it was grabbed, so the box doesn't jump to the pointer.
        anchor = (left, top) if mode == "move" else (right, bottom)
        self._drag = (mode, tag, event.x - anchor[0], event.y - anchor[1])

    def _drag_to(self, event):
        if self._drag is None:
            return
        mode, tag, dx, dy = self._drag
        box = self.boxes[tag]
        x0, y0, _x1, _y1 = self.screen
        sw, sh = self._screen_size()
        fx, fy = (event.x - dx - x0) / sw, (event.y - dy - y0) / sh
        if mode == "move":
            # Top-left follows the pointer; the whole box stays on the screen.
            box["x"] = _clamp(fx, 0.0, 1.0 - box["w"])
            box["y"] = _clamp(fy, 0.0, 1.0 - box["h"])
        else:
            # Bottom-right follows the pointer; top-left stays put.
            box["w"] = _clamp(fx - box["x"], MIN_W, 1.0 - box["x"])
            box["h"] = _clamp(fy - box["y"], MIN_H, 1.0 - box["y"])
        self._redraw(tag)

    def _end_drag(self, _event):
        if self._drag is not None:
            self._drag = None
            self._changed()

    def _update_hint(self):
        self.itemconfig(self.empty_hint, state="hidden" if self.boxes else "normal")

    def _changed(self):
        self.on_change(self.layout())

    def layout(self):
        return [dict(box) for box in self.boxes.values()]


class PhoneLayoutWindow:
    """The editor window. open() shows it, or brings an open one to the front."""

    def __init__(self, parent):
        self.parent = parent
        self.win = None
        self.phone = None  # the PhoneCanvas while the window is open
        # Current layout, kept in memory so the receiver can send it to the
        # phone every refresh without reading the file each time.
        self.layout = load_layout()

    def open(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify()
            self.win.lift()
            return
        self.win = win = tk.Toplevel(self.parent)
        win.title("Tilt Wheel - Phone layout")
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self.close)

        pad = {"padx": 12, "pady": 8}
        left = tk.LabelFrame(win, text="Controller (click a button to add it, once)")
        left.pack(side="left", fill="y", **pad)
        # Reuse the Mac app's drawing; clicking a button adds a box instead of
        # waiting for a key, so the picking state is cleared straight away.
        self.controller = ControllerView(left, {})
        self.controller.pack(padx=4, pady=4)
        self.controller.reset_btn.config(text="Clear phone", command=self._clear)
        self.controller.start_pick = self._add
        self.controller._refresh = self._paint_zone
        self.controller.hint.config(text="Each click adds one box. Filled = already on the phone.")

        right = tk.LabelFrame(win, text="Phone (drag to move, corner to resize, right-click to remove)")
        right.pack(side="left", fill="both", expand=True, **pad)
        self.phone = PhoneCanvas(right, self.layout, on_change=self._changed)
        self.phone.pack(padx=8, pady=8, expand=True)
        self.status = tk.Label(right, anchor="w", fg=app_common.muted(win))
        self.status.pack(fill="x", padx=8, pady=(0, 6))
        self._update_status()
        self.controller._refresh_all()

    def _placed(self):
        return {box["target"] for box in self.layout}

    def _paint_zone(self, target):
        """Controller drawing: a button already on the phone is filled in
        (face buttons in their own colour), so you can see what's used."""
        view = self.controller
        used = target in self._placed()
        fill = (FACE_COLORS.get(target, ADDED_COLOR) if used else view.colors["button"])
        view.canvas.itemconfig(view.shapes[target], fill=fill)
        if used:
            label, color, font = BOX_LABELS.get(target, target), "white", ("Helvetica", 8, "bold")
        elif target in FACE_COLORS:
            label, color, font = target, FACE_COLORS[target], ("Helvetica", 11, "bold")
        else:
            label, color, font = "", view.colors["key_text"], ("Helvetica", 8)
        view.canvas.itemconfig(view.labels[target], text=label, fill=color, font=font)

    def _changed(self, layout):
        """Any add, move, remove or clear: save, recolour the controller, and
        refresh the count."""
        self.layout = layout
        save_layout(layout)
        if hasattr(self, "status"):
            self.controller._refresh_all()
            self._update_status()

    def _add(self, target):
        if target in self._placed():
            # One box per button: a second would just press the same thing.
            self._update_status(f"{TARGET_NAMES[target]} is already on the phone "
                                "(right-click its box to remove it).")
            return
        self.phone.add_box(target)
        self._update_status(f"Added {TARGET_NAMES[target]}.")

    def _clear(self):
        self.phone.clear()
        self._update_status("Cleared.")

    def _update_status(self, note=""):
        count = len(self.phone.boxes)
        text = f"{count} box{'es' if count != 1 else ''} on the phone. Saved automatically."
        self.status.config(text=f"{note}  {text}".strip())

    def close(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.destroy()
        self.win = None
        self.phone = None


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    editor = PhoneLayoutWindow(root)
    editor.open()
    editor.win.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
