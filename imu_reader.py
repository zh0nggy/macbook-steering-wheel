"""Thin wrapper over macimu 0.2.0's real API. Mac only. Needs sudo.

Written against the API surface printed by macimu 0.2.0:
    IMU: start, stop, read_accel, read_gyro, read_all, latest_accel,
         latest_gyro, orientation, available, mock, from_recording, record_to
    Sample:      (x, y, z, count, index)
    Orientation: (roll, pitch, yaw, qw, qx, qy, qz, count, index)

macimu ships a Mahony AHRS filter and exposes fused roll/pitch/yaw through
`IMU.orientation`, so we do NOT need to write our own complementary filter for
steering -- see pick_roll_source() below.
"""

import macimu


class Imu:
    """Wraps macimu.IMU with a stable interface for our two scripts."""

    def __init__(self):
        self.imu = macimu.IMU()
        self._orientation_is_callable = None

    def start(self):
        try:
            self.imu.start()
        except PermissionError as exc:
            raise SystemExit(
                f"{exc}\n\nRe-run with sudo:\n    sudo python3 {_script_name()}\n\n"
                "VS Code's F5 cannot do this -- use the integrated terminal."
            )
        except Exception as exc:
            raise SystemExit(
                f"Could not start the IMU: {exc!r}\n"
                "If this says the sensor was not found, this Mac may not expose it."
            )

    def stop(self):
        try:
            self.imu.stop()
        except Exception:
            pass

    def accel(self):
        """(x, y, z) in g, or None if no sample is available yet."""
        return _xyz(self.imu.read_accel) or _xyz_attr(self.imu, "latest_accel")

    def gyro(self):
        """(x, y, z) angular velocity, or None."""
        return _xyz(self.imu.read_gyro) or _xyz_attr(self.imu, "latest_gyro")

    def orientation(self):
        """Fused (roll, pitch, yaw) in degrees, or None if unsupported.

        `orientation` may be a property or a method depending on version, so we
        probe once and remember which it is.
        """
        try:
            if self._orientation_is_callable is None:
                attr = getattr(type(self.imu), "orientation", None)
                self._orientation_is_callable = not isinstance(attr, property)
            value = self.imu.orientation
            if self._orientation_is_callable and callable(value):
                value = value()

            batch = _as_batch(value)
            if not batch:
                return None
            # Take the NEWEST, do not average. Averaging angles is wrong near
            # the wrap point: mean(+179, -179) = 0, i.e. the opposite direction.
            newest = batch[-1]
            return (
                float(newest.roll),
                float(newest.pitch),
                float(newest.yaw),
            )
        except Exception:
            return None

    def sample_rate(self):
        try:
            rate = self.imu.effective_sample_rate
            return float(rate() if callable(rate) else rate)
        except Exception:
            return None


def _mean_xyz(batch):
    """Average a batch of Samples into one (x, y, z) tuple.

    macimu's read_* methods return a LIST of every sample buffered since the
    last call -- the sensor runs at ~800 Hz, so at our 100 Hz send rate each
    call yields roughly 8 of them.

    Averaging rather than taking the newest is deliberate: all the samples in a
    batch are from the same ~10 ms window, so the mean cuts sensor noise without
    costing any latency. This is decimation, and it's free.
    """
    total = [0.0, 0.0, 0.0]
    count = 0
    for sample in batch:
        try:
            total[0] += float(sample.x)
            total[1] += float(sample.y)
            total[2] += float(sample.z)
            count += 1
        except (AttributeError, TypeError, ValueError):
            continue
    if count == 0:
        return None
    return (total[0] / count, total[1] / count, total[2] / count)


def _as_batch(value):
    """Normalise a read_* return value into a list of Samples."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]  # some versions may hand back a single Sample


def _xyz(reader):
    try:
        return _mean_xyz(_as_batch(reader()))
    except Exception:
        return None


def _xyz_attr(imu, name):
    try:
        return _mean_xyz(_as_batch(getattr(imu, name)))
    except Exception:
        return None


def _script_name():
    import os
    import sys

    return os.path.basename(sys.argv[0]) or "imu_probe.py"


def check_available():
    """True/False/None -- whether macimu thinks this Mac has the sensor."""
    try:
        fn = getattr(macimu, "check_available", None)
        if callable(fn):
            return bool(fn())
    except Exception:
        pass
    return None


def device_info():
    try:
        fn = getattr(macimu, "get_device_info", None)
        if callable(fn):
            return fn()
    except Exception:
        pass
    return None
