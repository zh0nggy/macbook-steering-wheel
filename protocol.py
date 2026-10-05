"""Frozen wire format between the Mac (sensor) and the Windows PC (virtual pad).

*** WIRE_VERSION 2 -- COPY THIS FILE TO BOTH MACHINES TOGETHER. ***

If the two copies differ, the receiver silently rejects every packet (version
mismatch) and you get a dead wheel with no error message. This is the one file
where a stale copy fails quietly instead of loudly.

v2 added gear_up / gear_down shift counters.
"""

import struct
import time

WIRE_VERSION = 2
DEFAULT_PORT = 5005

# version, timestamp, steer, throttle, brake, seq, gear_up, gear_down
#   steer            -1.0 (full left) .. +1.0 (full right)
#   throttle, brake   0.0 .. 1.0
#   gear_up/down      MONOTONIC COUNTERS, wrapping at 256 -- not booleans.
#                     See the note below; this matters.
_PACKET = struct.Struct("!BdfffIBB")
PACKET_SIZE = _PACKET.size

# WHY COUNTERS AND NOT BOOLEANS:
# Steering is a STATE -- sending 0.42 a hundred times a second just means "the
# wheel is still at 0.42". A gear shift is an EVENT. If we sent gear_up=True at
# 100 Hz while you held the key for 200 ms, the game would see ~20 upshifts and
# you would be in top gear instantly. So the sender increments a counter once
# per keypress, and the receiver pulses the button once whenever the number
# changes. Wrapping at 256 is fine: we only ever compare "is it different?".


def clamp(value, low, high):
    return low if value < low else high if value > high else value


def pack(steer, throttle=0.0, brake=0.0, seq=0, gear_up=0, gear_down=0,
         timestamp=None):
    """Serialise one control frame. Returns bytes ready for sendto()."""
    if timestamp is None:
        timestamp = time.monotonic()
    return _PACKET.pack(
        WIRE_VERSION,
        timestamp,
        clamp(float(steer), -1.0, 1.0),
        clamp(float(throttle), 0.0, 1.0),
        clamp(float(brake), 0.0, 1.0),
        seq & 0xFFFFFFFF,
        gear_up & 0xFF,
        gear_down & 0xFF,
    )


def unpack(data):
    """Deserialise one control frame.

    Returns a dict, or None if the packet is the wrong size or wrong version.
    Returning None rather than raising keeps the receive loop simple: bad
    packets are dropped and the failsafe handles the gap.
    """
    if len(data) != PACKET_SIZE:
        return None
    version, timestamp, steer, throttle, brake, seq, gear_up, gear_down = (
        _PACKET.unpack(data)
    )
    if version != WIRE_VERSION:
        return None
    return {
        "timestamp": timestamp,
        "steer": steer,
        "throttle": throttle,
        "brake": brake,
        "seq": seq,
        "gear_up": gear_up,
        "gear_down": gear_down,
    }
