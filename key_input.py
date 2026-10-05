"""Mac-side keyboard capture for throttle, brake and gear shifts.

    pip3 install pynput

Needs macOS Input Monitoring permission. You are already running under sudo,
which usually satisfies it; if not, grant it to Terminal (or VS Code) under
System Settings -> Privacy & Security -> Input Monitoring.

Keys are captured GLOBALLY, so they fire regardless of which window has focus.
Two consequences worth knowing: it works even though the game is on the other
machine, and the keystrokes ALSO reach whatever app is focused on the Mac. Keep
a scratch window focused, not something you care about.
"""

import threading
import time

try:
    from pynput import keyboard as _kb
except ImportError:  # pragma: no cover
    _kb = None


# Names accepted for --key-* flags. Single characters work too ("z", "x").
# "shift" is the LEFT shift; "shift_r" is the right one. Same for cmd/alt/ctrl.
SPECIAL_KEYS = {
    "up", "down", "left", "right",
    "space", "enter", "tab", "esc", "backspace", "delete",
    "shift", "shift_r",
    "cmd", "cmd_r",
    "alt", "alt_r",
    "ctrl", "ctrl_r",
    "caps_lock",
}

# Keys the OS treats as LOCKING modifiers. They do not report hold state -- one
# physical press latches them on, the next press releases. Fine as a toggle,
# useless as a pedal you hold down.
TOGGLE_KEYS = {"caps_lock"}

# Things people naturally type -> what pynput actually calls them.
ALIASES = {
    "return": "enter",
    "capslock": "caps_lock",
    "caps": "caps_lock",
    "lshift": "shift",
    "leftshift": "shift",
    "shift_l": "shift",
    "rshift": "shift_r",
    "rightshift": "shift_r",
    "escape": "esc",
    "spacebar": "space",
    "option": "alt",
    "control": "ctrl",
    "command": "cmd",
}


def validate(name, role, must_be_holdable=False):
    """Resolve aliases and fail loudly on a bad key name.

    Without this a typo like "leftshift" simply never matches anything, and you
    get a key that silently does nothing -- far harder to spot than an error.
    """
    lowered = ALIASES.get(name.lower(), name.lower())

    if must_be_holdable and lowered in TOGGLE_KEYS:
        raise SystemExit(
            f"\n{name} cannot be used for {role}.\n\n"
            "macOS treats it as a LOCKING modifier: it reports on/off toggle\n"
            "events, not press-and-hold. As a pedal you would press once for\n"
            "full throttle forever, then press again to lift -- no partial\n"
            "input and no way to feather it.\n\n"
            "Try shift_r (right shift) instead.\n"
        )

    if len(lowered) == 1 or lowered in SPECIAL_KEYS:
        return lowered

    raise SystemExit(
        f"\nUnknown key {name!r} for {role}.\n"
        f"Use a single character, or one of:\n  {', '.join(sorted(SPECIAL_KEYS))}\n"
    )


def _key_name(key):
    """Normalise a pynput key event into a lowercase string we can compare."""
    try:
        char = key.char
        if char:
            return char.lower()
    except AttributeError:
        pass
    name = getattr(key, "name", None)
    return name.lower() if name else None


class Keys:
    """Tracks which of our bound keys are currently held.

    Throttle and brake are STATES (held = applied), so we expose booleans.
    Gear shifts are EVENTS, so we expose monotonic counters that increment once
    per keypress -- see the note in protocol.py for why this distinction matters.
    """

    def __init__(
        self, throttle="shift", brake="enter", gear_up="tab", gear_down="shift_r"
    ):
        if _kb is None:
            raise SystemExit(
                "pynput not installed. Run:  pip3 install pynput\n"
                "(or run mac_sender.py with --no-keys to skip keyboard input)"
            )
        self.bindings = {
            # Throttle and brake must be holdable; gears only need a press.
            "throttle": validate(throttle, "throttle", must_be_holdable=True),
            "brake": validate(brake, "brake", must_be_holdable=True),
            "gear_up": validate(gear_up, "gear up"),
            "gear_down": validate(gear_down, "gear down"),
        }
        self._held = set()
        self._lock = threading.Lock()
        self.gear_up_count = 0
        self.gear_down_count = 0
        self._listener = None

    def start(self):
        self._listener = _kb.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._listener.daemon = True
        self._listener.start()
        # Give the event tap a moment to attach so a permission failure surfaces
        # here rather than as mysterious silence later.
        time.sleep(0.4)
        if not self._listener.running:
            raise SystemExit(
                "Keyboard listener failed to start. This is almost always the\n"
                "macOS Input Monitoring permission: System Settings ->\n"
                "Privacy & Security -> Input Monitoring -> enable your terminal.\n"
                "Or run with --no-keys to skip keyboard input."
            )

    def stop(self):
        if self._listener is not None:
            self._listener.stop()

    def _on_press(self, key):
        name = _key_name(key)
        if name is None:
            return
        with self._lock:
            if name in self._held:
                return  # ignore auto-repeat: one press = one shift
            self._held.add(name)
            if name == self.bindings["gear_up"]:
                self.gear_up_count = (self.gear_up_count + 1) & 0xFF
            elif name == self.bindings["gear_down"]:
                self.gear_down_count = (self.gear_down_count + 1) & 0xFF

    def _on_release(self, key):
        name = _key_name(key)
        if name is None:
            return
        with self._lock:
            self._held.discard(name)

    def state(self):
        """(throttle_held, brake_held, gear_up_count, gear_down_count)."""
        with self._lock:
            return (
                self.bindings["throttle"] in self._held,
                self.bindings["brake"] in self._held,
                self.gear_up_count,
                self.gear_down_count,
            )


class Ramp:
    """Turns a held key into a smooth 0..1 value.

    A key is binary, but throttle and brake are analog. Slamming straight to
    1.0 makes the car undriveable -- it just spins the wheels. This ramps up
    while held and decays when released, which is much closer to how a pedal
    behaves.
    """

    def __init__(self, rise_seconds=0.35, fall_seconds=0.18):
        self.value = 0.0
        self.rise = 1.0 / max(rise_seconds, 1e-3)
        self.fall = 1.0 / max(fall_seconds, 1e-3)

    def update(self, held, dt):
        if held:
            self.value = min(1.0, self.value + self.rise * dt)
        else:
            self.value = max(0.0, self.value - self.fall * dt)
        return self.value
