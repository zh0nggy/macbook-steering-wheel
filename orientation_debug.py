"""Why is fused orientation unavailable? Mac only, needs sudo.

    sudo python3 orientation_debug.py

Paste the whole output back. imu_reader.py catches exceptions and returns None,
which hides the actual reason -- this script deliberately does not.
"""

import inspect
import time

import macimu


def show(label, fn):
    try:
        print(f"{label}: {fn()!r}")
    except Exception as exc:
        print(f"{label}: RAISED {exc!r}")


print("--- constructor / start signatures ---")
# If either takes an `orientation=` or `fusion=` kwarg, that's our answer.
for name, obj in (("IMU.__init__", macimu.IMU.__init__), ("IMU.start", macimu.IMU.start)):
    try:
        print(f"{name}{inspect.signature(obj)}")
    except Exception as exc:
        print(f"{name}: signature unavailable ({exc!r})")

print("\n--- is IMU.orientation a property or a method? ---")
attr = getattr(macimu.IMU, "orientation", None)
print(f"type: {type(attr)}")
print(f"is property: {isinstance(attr, property)}")
doc = getattr(attr, "__doc__", None)
if doc:
    print(f"docstring: {doc.strip()[:400]}")

print("\n--- module-level `orientation` ---")
mod_orientation = getattr(macimu, "orientation", None)
print(f"type: {type(mod_orientation)}")
if callable(mod_orientation):
    try:
        print(f"signature: {inspect.signature(mod_orientation)}")
    except Exception as exc:
        print(f"signature unavailable ({exc!r})")
if mod_orientation is not None:
    print(f"members: {[n for n in dir(mod_orientation) if not n.startswith('_')][:25]}")

print("\n--- live sensor read ---")
imu = macimu.IMU()
imu.start()
time.sleep(1.0)  # longer than imu_reader's 0.3s, in case fusion needs warm-up

show("read_accel()", imu.read_accel)
show("read_gyro()", imu.read_gyro)
show("read_all()", imu.read_all)
show("orientation (raw attr)", lambda: imu.orientation)
show("effective_sample_rate", lambda: imu.effective_sample_rate)
show("available", lambda: imu.available)

print("\n--- does the gyro actually move? ---")
print("ROTATE THE LAPTOP NOW for 3 seconds...")
peak = 0.0
reads = 0
none_reads = 0
deadline = time.monotonic() + 3.0
while time.monotonic() < deadline:
    try:
        g = imu.read_gyro()
    except Exception as exc:
        print(f"read_gyro raised {exc!r}")
        break
    if g is None:
        none_reads += 1
    else:
        reads += 1
        magnitude = (g.x ** 2 + g.y ** 2 + g.z ** 2) ** 0.5
        peak = max(peak, magnitude)
    time.sleep(0.01)

print(f"gyro reads: {reads} good, {none_reads} empty, peak magnitude {peak:.3f}")
if peak > 0.05:
    print(">>> GYRO IS LIVE. We can run MahonyAHRS by hand.")
else:
    print(">>> No gyro motion detected. Accelerometer-only it is.")

print("\n--- can we drive MahonyAHRS ourselves? ---")
try:
    ahrs = macimu.MahonyAHRS()
    print(f"MahonyAHRS() constructed: {ahrs!r}")
    print(f"update signature: {inspect.signature(ahrs.update)}")
    print(f"euler signature: {inspect.signature(ahrs.euler) if callable(getattr(ahrs, 'euler', None)) else 'property'}")
except Exception as exc:
    print(f"MahonyAHRS unusable: {exc!r}")

imu.stop()
print("\ndone -- paste all of the above")
