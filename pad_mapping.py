"""Which virtual-pad input each control drives, plus per-game presets.

The receiver always creates a standard Xbox 360 pad, which nearly every PC
game understands. What differs between games is the binding: Assetto Corsa
shifts on A/X, Forza on B/X, many others on the bumpers. Rather than hardcode
one game, the receiver looks the outputs up here.

Pure data + one apply() function, so it can be tested without vgamepad.
"""

# Steering goes on a stick's X axis.
STEER_TARGETS = {
    "Left stick X": "left",
    "Right stick X": "right",
}

# Pedals can go on a trigger or half of a stick's Y axis. Some games (and many
# emulators) want throttle on stick-up and brake on stick-down.
PEDAL_TARGETS = {
    "Right trigger": ("rt", 0),
    "Left trigger": ("lt", 0),
    "Left stick up": ("left", +1),
    "Left stick down": ("left", -1),
    "Right stick up": ("right", +1),
    "Right stick down": ("right", -1),
    "None": None,
}

# Display name -> vgamepad XUSB_BUTTON attribute.
BUTTONS = {
    "A": "XUSB_GAMEPAD_A",
    "B": "XUSB_GAMEPAD_B",
    "X": "XUSB_GAMEPAD_X",
    "Y": "XUSB_GAMEPAD_Y",
    "RB (right bumper)": "XUSB_GAMEPAD_RIGHT_SHOULDER",
    "LB (left bumper)": "XUSB_GAMEPAD_LEFT_SHOULDER",
    "D-pad up": "XUSB_GAMEPAD_DPAD_UP",
    "D-pad down": "XUSB_GAMEPAD_DPAD_DOWN",
    "D-pad left": "XUSB_GAMEPAD_DPAD_LEFT",
    "D-pad right": "XUSB_GAMEPAD_DPAD_RIGHT",
    "Start": "XUSB_GAMEPAD_START",
    "Back": "XUSB_GAMEPAD_BACK",
    "Left stick click": "XUSB_GAMEPAD_LEFT_THUMB",
    "Right stick click": "XUSB_GAMEPAD_RIGHT_THUMB",
    "None": None,
}

ROLES = ("steer", "throttle", "brake", "button_1", "button_2")

PRESETS = {
    "Assetto Corsa": {"steer": "Left stick X", "throttle": "Right trigger",
                      "brake": "Left trigger", "button_1": "A", "button_2": "X"},
    "Forza (Horizon / Motorsport)": {"steer": "Left stick X", "throttle": "Right trigger",
                                     "brake": "Left trigger", "button_1": "B",
                                     "button_2": "X"},
    "Generic: bumpers shift": {"steer": "Left stick X", "throttle": "Right trigger",
                               "brake": "Left trigger", "button_1": "RB (right bumper)",
                               "button_2": "LB (left bumper)"},
    "Generic: stick pedals": {"steer": "Left stick X", "throttle": "Right stick up",
                              "brake": "Right stick down", "button_1": "RB (right bumper)",
                              "button_2": "LB (left bumper)"},
}
CUSTOM = "Custom"
DEFAULT_PRESET = "Assetto Corsa"


def preset_for(mapping):
    """Name of the preset that exactly matches `mapping`, else CUSTOM."""
    for name, preset in PRESETS.items():
        if all(mapping.get(role) == preset[role] for role in ROLES):
            return name
    return CUSTOM


def sanitize(mapping):
    """Fill missing/unknown entries from the default preset (old or hand-edited
    settings files must not crash the receiver)."""
    base = PRESETS[DEFAULT_PRESET]
    choices = {"steer": STEER_TARGETS, "throttle": PEDAL_TARGETS, "brake": PEDAL_TARGETS,
               "button_1": BUTTONS, "button_2": BUTTONS}
    return {role: mapping.get(role) if mapping.get(role) in choices[role] else base[role]
            for role in ROLES}


def compute(mapping, steer, throttle, brake):
    """Mapping + control values -> {"left": (x, y), "right": (x, y), "lt": v, "rt": v}."""
    sticks = {"left": [0.0, 0.0], "right": [0.0, 0.0]}
    triggers = {"lt": 0.0, "rt": 0.0}
    sticks[STEER_TARGETS[mapping["steer"]]][0] += steer
    for value, role in ((throttle, "throttle"), (brake, "brake")):
        target = PEDAL_TARGETS[mapping[role]]
        if target is None:
            continue
        name, direction = target
        if name in triggers:
            triggers[name] = max(triggers[name], value)  # both on one trigger: stronger wins
        else:
            sticks[name][1] += direction * value

    def clamp(v):
        return max(-1.0, min(1.0, v))

    return {"left": (clamp(sticks["left"][0]), clamp(sticks["left"][1])),
            "right": (clamp(sticks["right"][0]), clamp(sticks["right"][1])),
            "lt": triggers["lt"], "rt": triggers["rt"]}


def apply(pad, mapping, steer, throttle, brake):
    out = compute(mapping, steer, throttle, brake)
    pad.left_joystick_float(x_value_float=out["left"][0], y_value_float=out["left"][1])
    pad.right_joystick_float(x_value_float=out["right"][0], y_value_float=out["right"][1])
    pad.left_trigger_float(value_float=out["lt"])
    pad.right_trigger_float(value_float=out["rt"])


class Pulse:
    """Presses a pad button briefly when a counter changes, without blocking.

    Same idea as pad_receiver.ButtonPulse, but the button is passed per call so
    the mapping can change live, and it remembers WHICH button it pressed so a
    remap mid-press still releases the right one.
    """

    def __init__(self, hold_seconds=0.07):
        self.hold = hold_seconds
        self.last_count = None
        self.pressed = None
        self.release_at = None

    def check(self, count, pad, button, now):
        """Returns True if this call fired a press."""
        if self.last_count is None:
            self.last_count = count  # adopt sender's value; no phantom press on restart
            return False
        if count == self.last_count:
            return False
        self.last_count = count
        self.fire(pad, button, now)
        return True

    def fire(self, pad, button, now):
        self.release(pad)
        if button is None:
            return
        if pad is not None:
            pad.press_button(button=button)
        self.pressed = button
        self.release_at = now + self.hold

    def maybe_release(self, pad, now):
        if self.release_at is not None and now >= self.release_at:
            self.release(pad)

    def release(self, pad):
        if self.pressed is not None and pad is not None:
            pad.release_button(button=self.pressed)
        self.pressed = None
        self.release_at = None
