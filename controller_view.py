"""Clickable Xbox-controller picture for binding Mac keys to pad buttons.

Click a button on the drawing, then press the key you want for it. Escape
cancels, Backspace/Delete clears the binding. Each button shows its key, and
lights up while that key is held, so you can see what reaches the PC.

Bindings are {target: tk keysym}. Targets are the protocol.BUTTONS names plus
"RT" and "LT" for the analog triggers (held key = pedal ramps up).
"""

import tkinter as tk

from app_common import is_dark

# Display names for keysyms (Tk names -> what's printed on the key).
# Short enough to fit inside the small round buttons.
KEY_LABELS = {
    "Shift_L": "LShf", "Shift_R": "RShf", "Control_L": "LCtl",
    "Control_R": "RCtl", "Alt_L": "LOpt", "Alt_R": "ROpt",
    "Meta_L": "LCmd", "Meta_R": "RCmd", "Super_L": "LCmd", "Super_R": "RCmd",
    "Return": "Ret", "Tab": "Tab", "space": "Spc", "BackSpace": "Bksp",
    "Up": "↑", "Down": "↓", "Left": "←", "Right": "→",
    "comma": ",", "period": ".", "slash": "/", "semicolon": ";",
    "apostrophe": "'", "bracketleft": "[", "bracketright": "]",
    "minus": "-", "equal": "=", "grave": "`", "backslash": "\\",
}

WIDE_LABELS = {
    "Shift_L": "Left Shift", "Shift_R": "Right Shift", "Control_L": "Left Ctrl",
    "Control_R": "Right Ctrl", "Alt_L": "Left Option", "Alt_R": "Right Option",
    "Meta_L": "Left Cmd", "Meta_R": "Right Cmd", "Super_L": "Left Cmd",
    "Super_R": "Right Cmd", "Return": "Return", "space": "Space",
    "Up": "Up arrow", "Down": "Down arrow", "Left": "Left arrow", "Right": "Right arrow",
}

# Keys that can't be bound: they control the binding itself, or macOS latches
# them instead of reporting hold (caps lock), which would make a stuck button.
RESERVED = {"Escape", "BackSpace", "Delete", "Caps_Lock"}

TARGET_NAMES = {
    "A": "A", "B": "B", "X": "X", "Y": "Y",
    "LB": "Left bumper", "RB": "Right bumper",
    "LT": "Left trigger", "RT": "Right trigger",
    "VIEW": "View", "MENU": "Menu", "GUIDE": "Xbox button",
    "LS": "Left stick click", "RS": "Right stick click",
    "DPAD_UP": "D-pad up", "DPAD_DOWN": "D-pad down",
    "DPAD_LEFT": "D-pad left", "DPAD_RIGHT": "D-pad right",
}

# Defaults: pedals and gears where the old hardcoded keys were.
DEFAULT_BINDINGS = {"RT": "Shift_L", "LT": "Return", "A": "Tab", "X": "Shift_R"}


def key_label(keysym):
    if keysym is None:
        return ""
    if keysym in KEY_LABELS:
        return KEY_LABELS[keysym]
    if len(keysym) == 1:
        return keysym.upper()
    return keysym[:4]  # e.g. F5, KP_1 -> fits the button


def normalise(keysym):
    """Tk keysym -> the name we store. Letters are case-folded so Shift+A
    doesn't count as a different key from A."""
    return keysym.lower() if len(keysym) == 1 else keysym


# Two palettes; ControllerView picks one from the window's real background so
# the drawing blends in with light and dark mode (macOS dark mode included).
LIGHT = {
    "outline": "#555", "body": "#e9e9e9", "ring": "#d6d6d6", "button": "#ffffff",
    "bound": "#dbe9fb", "held": "#2b7de9", "picking": "#ffd75e",
    "key_text": "#222", "label": "#777", "hint": "#555", "hint_active": "#b06000",
}
DARK = {
    "outline": "#9a9a9a", "body": "#46464a", "ring": "#2c2c2e", "button": "#636368",
    "bound": "#2f4f78", "held": "#2b7de9", "picking": "#c79a1e",
    "key_text": "#f2f2f2", "label": "#9a9a9a", "hint": "#a8a8a8", "hint_active": "#f0a63a",
}
FACE_COLORS = {"A": "#2fa84f", "B": "#d64545", "X": "#2b7de9", "Y": "#d9a400"}




class ControllerView(tk.Frame):
    """The drawing plus a one-line hint underneath.

    on_change(bindings) is called whenever a binding is set or cleared.
    """

    TRIGGER_TOP = 10   # where _draw puts the trigger row
    ROW_GAP = 13       # gap between rows: Reset -> triggers -> bumpers -> body
    # Starting height; __init__ trims the canvas to fit the finished drawing.
    W, H = 440, 400

    def __init__(self, parent, bindings, on_change=None):
        super().__init__(parent)
        self.bindings = dict(bindings)
        self.on_change = on_change
        self.picking = None
        self.held_targets = set()
        self.listeners = []
        self.shapes = {}   # target -> canvas item to recolour
        self.labels = {}   # target -> canvas text item for the key name

        # Same background as the window, so the drawing sits on it rather than
        # in a pale box; then colours to suit a light or dark window.
        self.colors = DARK if is_dark(self) else LIGHT
        self.canvas = tk.Canvas(self, width=self.W, height=self.H, bg=self.cget("bg"),
                                highlightthickness=0)
        self.canvas.pack()
        self.hint = tk.Label(self, anchor="w", justify="left", fg=self.colors["hint"])
        self.hint.pack(fill="x", pady=(2, 0))
        # Reset goes in a strip above the drawing, top-right corner.
        self.reset_btn = tk.Button(self.canvas, text="Reset to defaults",
                                   command=self.reset)
        self.canvas.create_window(self.W - 4, 3, window=self.reset_btn, anchor="ne")
        self._draw()
        # Bumpers end at y=74; drop the body (and everything on it) so its top
        # edge is one ROW_GAP below them.
        body_shift = 74 + self.ROW_GAP - self.BODY_TOP
        for item in self.canvas.find_all():
            if self.canvas.type(item) != "window" and self.canvas.bbox(item)[1] >= 76:
                self.canvas.move(item, 0, body_shift)
        self.body_shift = body_shift
        # Same gap under Reset as between the trigger and bumper rows (and
        # bumpers -> body). Measured, because the button's height depends on
        # the platform font.
        top = 3 + self.reset_btn.winfo_reqheight() + self.ROW_GAP - self.TRIGGER_TOP
        drawn = [i for i in self.canvas.find_all() if self.canvas.type(i) != "window"]
        for item in drawn:
            self.canvas.move(item, 0, top)
        # So fit_height() redraws the body where it now sits.
        self.offset = top + body_shift
        # Fit the canvas to the drawing; fit_height() can stretch it later.
        lowest = max(self.canvas.bbox(i)[3] for i in drawn)
        self._natural_height = lowest + 2
        self.canvas.config(height=self._natural_height)
        self._refresh_all()
        self._set_hint()

    # ---------- drawing ----------

    # Controller outline traced as one smooth polygon (x, y), left half only;
    # the right half is mirrored. Roughly the Xbox Series pad silhouette.
    # The top edge sits above the Y button and the shoulders are wide enough
    # that X/B and the sticks have clearance. y values below BODY_SPLIT are
    # the grips: _fit_body() stretches them to fill the available height.
    _HALF_OUTLINE = [
        (220, 80), (150, 80), (106, 85), (76, 98), (54, 120), (40, 152),
        (30, 190), (22, 232), (20, 268), (28, 292), (48, 302), (70, 296),
        (96, 270), (124, 240), (150, 226), (220, 226),
    ]
    BODY_TOP = 80      # top edge of the outline
    BODY_SPLIT = 210   # rows below this are the grips, which stretch

    def _draw(self):
        c = self.canvas
        mid = self.W / 2
        self.offset = 0  # _body_points adds this; __init__ sets it after the shift
        self.body = c.create_polygon(self._body_points(0), smooth=True, splinesteps=24,
                                     fill=self.colors["body"], outline=self.colors["outline"], width=2)

        # Triggers (back) and bumpers (top edge), labelled since they look alike.
        self._button("LT", c.create_rectangle(64, 10, 148, 36), (106, 23))
        self._button("RT", c.create_rectangle(292, 10, 376, 36), (334, 23))
        self._button("LB", c.create_rectangle(80, 50, 170, 74), (125, 62))
        self._button("RB", c.create_rectangle(270, 50, 360, 74), (315, 62))
        for text, x, y in (("LT", 56, 23), ("RT", 384, 23), ("LB", 72, 62), ("RB", 368, 62)):
            c.create_text(x, y, text=text, fill=self.colors["label"], font=("Helvetica", 8, "bold"),
                          anchor="e" if x < mid else "w")

        # Sticks: outer ring is the (unbindable) stick, inner disc is the click.
        for target, (x, y) in (("LS", (118, 140)), ("RS", (268, 190))):
            c.create_oval(x - 30, y - 30, x + 30, y + 30, fill=self.colors["ring"],
                          outline=self.colors["outline"], width=2)
            self._button(target, c.create_oval(x - 19, y - 19, x + 19, y + 19), (x, y))

        # D-pad: four arms around a centre square.
        cx, cy, a, w = 172, 190, 32, 12
        self._button("DPAD_UP", c.create_rectangle(cx - w, cy - a, cx + w, cy - w),
                     (cx, cy - a + 10))
        self._button("DPAD_DOWN", c.create_rectangle(cx - w, cy + w, cx + w, cy + a),
                     (cx, cy + a - 10))
        self._button("DPAD_LEFT", c.create_rectangle(cx - a, cy - w, cx - w, cy + w),
                     (cx - a + 10, cy))
        self._button("DPAD_RIGHT", c.create_rectangle(cx + w, cy - w, cx + a, cy + w),
                     (cx + a - 10, cy))
        c.create_rectangle(cx - w, cy - w, cx + w, cy + w, fill=self.colors["ring"], outline=self.colors["outline"])

        # Face buttons in the usual diamond, with coloured letters beside them.
        fx, fy, d, r = 334, 140, 27, 16
        for target, (x, y) in (("Y", (fx, fy - d)), ("B", (fx + d, fy)),
                               ("A", (fx, fy + d)), ("X", (fx - d, fy))):
            self._button(target, c.create_oval(x - r, y - r, x + r, y + r), (x, y))
            dx = {"X": -r - 7, "B": r + 7}.get(target, 0)
            dy = {"Y": -r - 7, "A": r + 7}.get(target, 0)
            c.create_text(x + dx, y + dy, text=target, fill=FACE_COLORS[target],
                          font=("Helvetica", 9, "bold"))

        # Centre: Xbox button with View / Menu either side.
        self._button("GUIDE", c.create_oval(mid - 17, 96, mid + 17, 130), (mid, 113))
        self._button("VIEW", c.create_oval(mid - 44, 136, mid - 22, 158), (mid - 33, 147))
        self._button("MENU", c.create_oval(mid + 22, 136, mid + 44, 158), (mid + 33, 147))

    def _body_points(self, stretch):
        """Outline coordinates with the grips pulled down by `stretch` px.
        Points below BODY_SPLIT move further the lower they are, so the grips
        lengthen smoothly instead of the whole body sliding."""
        mid = self.W / 2
        left = []
        for x, y in self._HALF_OUTLINE:
            if y > self.BODY_SPLIT:
                y += stretch * (y - self.BODY_SPLIT) / (302 - self.BODY_SPLIT)
            left.append((x, y + self.offset))
        right = [(2 * mid - x, y) for x, y in reversed(left)]
        return [coord for xy in left + right for coord in xy]

    MAX_STRETCH = 40   # past this the grips turn into stilts; pad instead

    def fit_height(self, height):
        """Make the drawing `height` px tall. The grips lengthen by up to
        MAX_STRETCH; any more is returned so the caller can pad with it.
        Called by the app once the window's real height is known."""
        natural = self._natural_height
        extra = max(0, height - natural)
        stretch = min(extra, self.MAX_STRETCH)
        self.canvas.coords(self.body, *self._body_points(stretch))
        self.canvas.config(height=natural + stretch)
        return extra - stretch

    def _button(self, target, item, text_at):
        c = self.canvas
        c.itemconfig(item, outline=self.colors["outline"], width=2, fill=self.colors["button"])
        text = c.create_text(*text_at, text="", font=("Helvetica", 8))
        self.shapes[target] = item
        self.labels[target] = text
        for tag in (item, text):
            c.tag_bind(tag, "<Button-1>", lambda _e, t=target: self.start_pick(t))
            c.tag_bind(tag, "<Enter>", lambda _e: c.config(cursor="hand2"))
            c.tag_bind(tag, "<Leave>", lambda _e: c.config(cursor=""))

    # ---------- state ----------

    def _refresh(self, target):
        col = self.colors
        if target == self.picking:
            state = "picking"
        elif target in self.held_targets:
            state = "held"
        elif target in self.bindings:
            state = "bound"
        else:
            state = "button"
        self.canvas.itemconfig(self.shapes[target], fill=col[state])
        key = self.bindings.get(target)
        # Triggers and bumpers are wide, so they get the full key name.
        wide = target in ("LT", "RT", "LB", "RB")
        text = "?" if target == self.picking else (
            WIDE_LABELS.get(key, key_label(key)) if wide else key_label(key))
        # Dark text on the light yellow "press a key" fill, else palette text.
        if state == "held":
            color = "white"
        elif state == "picking":
            color = "#222"
        else:
            color = col["key_text"]
        self.canvas.itemconfig(self.labels[target], text=text, fill=color)

    def _refresh_all(self):
        for target in self.shapes:
            self._refresh(target)

    def _set_hint(self, extra=""):
        if self.picking:
            text = (f"Press a key for {TARGET_NAMES[self.picking]}.  "
                    "Esc = cancel, Backspace = clear.")
        else:
            text = "Click a button on the controller, then press a Mac key for it."
        self.hint.config(text=text + (f"  {extra}" if extra else ""),
                         fg=self.colors["hint_active" if self.picking else "hint"])

    def start_pick(self, target):
        previous, self.picking = self.picking, target
        if previous:
            self._refresh(previous)
        self._refresh(target)
        self._set_hint()
        for callback in self.listeners:
            callback()

    def reset(self):
        self.set_bindings(DEFAULT_BINDINGS)

    def set_bindings(self, bindings):
        """Replace every binding at once (presets, Clear all, Reset)."""
        self.picking = None
        self.bindings = dict(bindings)
        self._changed()

    def add_listener(self, callback):
        """callback() runs after any binding or picking change, so other
        views (the game setup tab) can redraw."""
        self.listeners.append(callback)

    def _changed(self, note=""):
        self._refresh_all()
        self._set_hint(note)
        if self.on_change:
            self.on_change(dict(self.bindings))
        for callback in self.listeners:
            callback()

    def handle_key(self, keysym):
        """Called for every key press. Returns True if it was used for binding
        (so it must not also be treated as a game input)."""
        if self.picking is None:
            return False
        target, self.picking = self.picking, None
        note = ""
        if keysym == "Escape":
            pass
        elif keysym in ("BackSpace", "Delete"):
            self.bindings.pop(target, None)
        elif keysym in RESERVED:
            note = f"{key_label(keysym)} can't be used."
        else:
            key = normalise(keysym)
            # One key drives one button: move it off anything else first.
            for other, bound in list(self.bindings.items()):
                if bound == key and other != target:
                    del self.bindings[other]
                    note = f"(moved from {TARGET_NAMES[other]})"
            self.bindings[target] = key
        self._changed(note)
        return True

    def show_held(self, targets):
        """Light up the buttons whose keys are held right now."""
        targets = set(targets)
        if targets == self.held_targets:
            return
        changed = targets ^ self.held_targets
        self.held_targets = targets
        for target in changed:
            if target in self.shapes:
                self._refresh(target)
