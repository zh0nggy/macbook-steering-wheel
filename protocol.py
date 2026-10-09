"""Frozen wire format between the Mac (sensor) and the Windows PC (virtual pad).

*** WIRE_VERSION 3 -- COPY THIS FILE TO BOTH MACHINES TOGETHER. ***

If the two copies differ, the receiver silently rejects every packet (version
mismatch) and you get a dead wheel with no error message. This is the one file
where a stale copy fails quietly instead of loudly.

v2 added gear_up / gear_down shift counters.
v3 replaced them with a bitmask of every Xbox pad button, so the Mac can bind
   any key to any button. The two triggers keep their own analog values.
"""

import struct
import time

WIRE_VERSION = 3
DEFAULT_PORT = 5005

# version, timestamp, steer, right_trigger, left_trigger, seq, buttons
#   steer              -1.0 (full left) .. +1.0 (full right), left stick X
#   right/left trigger  0.0 .. 1.0 (analog, ramped on the Mac)
#   buttons             bitmask, bit set = button HELD right now (see BUTTONS)
_PACKET = struct.Struct("!BdfffIH")
PACKET_SIZE = _PACKET.size

# Bit order of the `buttons` field. Names match pad_mapping / vgamepad.
BUTTONS = (
    "A", "B", "X", "Y",
    "LB", "RB",
    "VIEW", "MENU", "GUIDE",
    "LS", "RS",
    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
)
BUTTON_BIT = {name: 1 << i for i, name in enumerate(BUTTONS)}

# WHY HELD STATE IS SAFE NOW:
# v2 sent counters because a shift is an event: sending "gear_up=True" at
# 100 Hz while a key is held must not mean 20 upshifts. With a real pad button
# that problem doesn't exist -- the receiver presses the button while the bit
# is set and releases it when it clears, exactly like a physical button held
# down. The game sees one press per key press. The Mac ignores keyboard
# auto-repeat, and the receiver's failsafe releases everything if packets stop.


def clamp(value, low, high):
    return low if value < low else high if value > high else value


def pack(steer, right_trigger=0.0, left_trigger=0.0, seq=0, buttons=0,
         timestamp=None):
    """Serialise one control frame. Returns bytes ready for sendto()."""
    if timestamp is None:
        timestamp = time.monotonic()
    return _PACKET.pack(
        WIRE_VERSION,
        timestamp,
        clamp(float(steer), -1.0, 1.0),
        clamp(float(right_trigger), 0.0, 1.0),
        clamp(float(left_trigger), 0.0, 1.0),
        seq & 0xFFFFFFFF,
        buttons & 0xFFFF,
    )


def unpack(data):
    """Deserialise one control frame.

    Returns a dict, or None if the packet is the wrong size or wrong version.
    Returning None rather than raising keeps the receive loop simple: bad
    packets are dropped and the failsafe handles the gap.
    """
    if len(data) != PACKET_SIZE:
        return None
    version, timestamp, steer, rt, lt, seq, buttons = _PACKET.unpack(data)
    if version != WIRE_VERSION:
        return None
    return {
        "timestamp": timestamp,
        "steer": steer,
        "right_trigger": rt,
        "left_trigger": lt,
        "seq": seq,
        "buttons": buttons,
    }
