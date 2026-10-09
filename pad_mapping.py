"""Turns a v3 control frame into virtual Xbox 360 pad state on Windows.

Which key does what is decided on the Mac now (the controller picture in the
sender app). The receiver just mirrors it: tilt -> left stick X, the two
trigger values -> the triggers, and every held button bit -> that pad button
held down. Pure data + small functions, so it can be tested without vgamepad.
"""

import protocol

# protocol.BUTTONS name -> vgamepad XUSB_BUTTON attribute.
XUSB = {
    "A": "XUSB_GAMEPAD_A",
    "B": "XUSB_GAMEPAD_B",
    "X": "XUSB_GAMEPAD_X",
    "Y": "XUSB_GAMEPAD_Y",
    "LB": "XUSB_GAMEPAD_LEFT_SHOULDER",
    "RB": "XUSB_GAMEPAD_RIGHT_SHOULDER",
    "VIEW": "XUSB_GAMEPAD_BACK",
    "MENU": "XUSB_GAMEPAD_START",
    "GUIDE": "XUSB_GAMEPAD_GUIDE",
    "LS": "XUSB_GAMEPAD_LEFT_THUMB",
    "RS": "XUSB_GAMEPAD_RIGHT_THUMB",
    "DPAD_UP": "XUSB_GAMEPAD_DPAD_UP",
    "DPAD_DOWN": "XUSB_GAMEPAD_DPAD_DOWN",
    "DPAD_LEFT": "XUSB_GAMEPAD_DPAD_LEFT",
    "DPAD_RIGHT": "XUSB_GAMEPAD_DPAD_RIGHT",
}
assert set(XUSB) == set(protocol.BUTTONS)


def held_buttons(mask):
    """Bitmask -> set of button names currently held."""
    return {name for name, bit in protocol.BUTTON_BIT.items() if mask & bit}


class ButtonState:
    """Keeps the pad's buttons in step with the bitmask.

    Only CHANGES are sent to the pad (press on 0->1, release on 1->0), so a
    button held for a second is one press to the game, like a real pad.
    """

    def __init__(self, resolve):
        self.resolve = resolve  # button name -> vgamepad button value
        self.held = set()
        self.presses = 0        # total presses, for the status line

    def update(self, pad, mask):
        target = held_buttons(mask)
        for name in target - self.held:
            self.presses += 1
            if pad is not None:
                pad.press_button(button=self.resolve(name))
        for name in self.held - target:
            if pad is not None:
                pad.release_button(button=self.resolve(name))
        self.held = target


def apply(pad, steer, right_trigger, left_trigger):
    pad.left_joystick_float(x_value_float=steer, y_value_float=0.0)
    pad.right_joystick_float(x_value_float=0.0, y_value_float=0.0)
    pad.right_trigger_float(value_float=right_trigger)
    pad.left_trigger_float(value_float=left_trigger)
