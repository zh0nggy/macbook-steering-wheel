"""Stand-in for macimu so the Mac sender can run on Windows (or any machine).

    python sender_app.py --demo

install() puts a fake `macimu` module in place before imu_reader imports it,
so everything after that -- imu_reader, the filter, networking, the window --
is the real code. The "sensor" just reports the roll angle from TILT, which
the demo window's slider sets. Small noise is added so the filter has
something to smooth, like the real sensor.
"""

import random
import sys
import time
import types

TILT = {"roll": 0.0}  # degrees; set by the demo slider
NOISE_DEG = 0.15
SAMPLE_RATE = 800.0   # the real sensor delivers ~800 samples/sec


class _Orientation:
    def __init__(self, roll):
        self.roll, self.pitch, self.yaw = roll, 0.0, 0.0


class _Sample:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class FakeIMU:
    def __init__(self):
        self._t0 = time.monotonic()

    def start(self):
        pass

    def stop(self):
        pass

    def _tick(self):
        # Quantise time so a "new sample" appears every 1.25 ms, and seed the
        # noise from the tick so repeated reads within one tick agree.
        tick = int((time.monotonic() - self._t0) * SAMPLE_RATE)
        return random.Random(tick).gauss(0.0, NOISE_DEG)

    @property
    def orientation(self):
        return [_Orientation(TILT["roll"] + self._tick())]

    def read_accel(self):
        # Gravity vector for the current roll, for accel-only mode (axes 0 / 2).
        import math
        rad = math.radians(TILT["roll"] + self._tick())
        return [_Sample(math.sin(rad), 0.0, math.cos(rad))]

    def read_gyro(self):
        return []


def install():
    sys.modules["macimu"] = types.SimpleNamespace(IMU=FakeIMU)
