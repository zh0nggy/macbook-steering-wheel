"""STEP 1. Runs on the MAC, needs sudo. Answers four questions:

    1. Does this M4 Air expose the IMU at all?
    2. Is the GYROSCOPE live, or accelerometer only?
    3. Does macimu's fused `orientation` (roll/pitch/yaw) work?
    4. WHICH AXIS IS WHICH -- discovered empirically, since Apple never
       documented this sensor.

    pip3 install macimu
    sudo python3 imu_probe.py

Hold the laptop the way you intend to steer, then ROLL it slowly left and
right (like tilting a tray -- not spinning it flat). Ctrl-C when done and read
the summary.
"""

import math
import sys
import time

import imu_reader


def main():
    available = imu_reader.check_available()
    print(f"check_available(): {available}")
    info = imu_reader.device_info()
    if info:
        print(f"device_info(): {info}")
    print()

    imu = imu_reader.Imu()
    imu.start()
    print("IMU started.\n")

    # Give the sensor worker a moment to produce its first samples.
    time.sleep(0.3)

    rate = imu.sample_rate()
    if rate:
        print(f"effective sample rate: {rate:.0f} Hz")

    orientation_works = imu.orientation() is not None
    print(f"fused orientation available: {orientation_works}")
    if orientation_works:
        print("  -> good: we can use macimu's Mahony filter instead of our own")
    else:
        print("  -> falling back to accelerometer-only roll (fine for the MVP)")

    print("\nRoll the laptop left and right now. Ctrl-C to finish.\n")

    accel_lo = [9e9] * 3
    accel_hi = [-9e9] * 3
    gyro_lo = [9e9] * 3
    gyro_hi = [-9e9] * 3
    roll_lo, roll_hi = 9e9, -9e9
    gyro_peak = 0.0
    samples = 0
    no_accel = 0
    last_print = 0.0

    try:
        while True:
            accel = imu.accel()
            gyro = imu.gyro()
            orient = imu.orientation() if orientation_works else None

            if accel is None:
                no_accel += 1
                time.sleep(0.005)
                continue

            samples += 1
            for i, v in enumerate(accel):
                accel_lo[i] = min(accel_lo[i], v)
                accel_hi[i] = max(accel_hi[i], v)

            gyro_magnitude = 0.0
            if gyro is not None:
                for i, v in enumerate(gyro):
                    gyro_lo[i] = min(gyro_lo[i], v)
                    gyro_hi[i] = max(gyro_hi[i], v)
                gyro_magnitude = math.sqrt(sum(v * v for v in gyro))
                gyro_peak = max(gyro_peak, gyro_magnitude)

            if orient is not None:
                roll_lo = min(roll_lo, orient[0])
                roll_hi = max(roll_hi, orient[0])

            now = time.monotonic()
            if now - last_print >= 0.2:
                ax, ay, az = accel
                norm = math.sqrt(ax * ax + ay * ay + az * az)
                gtext = (
                    f"gyro {gyro[0]:+7.2f} {gyro[1]:+7.2f} {gyro[2]:+7.2f}"
                    if gyro is not None
                    else "gyro    --      --      --"
                )
                moving = "YES" if gyro_magnitude > 0.05 else "NO "
                rtext = f" roll {orient[0]:+6.1f}" if orient is not None else ""
                sys.stdout.write(
                    f"\raccel {ax:+6.2f} {ay:+6.2f} {az:+6.2f} |{norm:4.2f}|  "
                    f"{gtext} move={moving}{rtext}  n={samples}   "
                )
                sys.stdout.flush()
                last_print = now

            time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        imu.stop()

    print("\n\n" + "=" * 62)
    if samples == 0:
        print("NO SAMPLES READ. The sensor started but produced nothing.")
        print(f"(read_accel returned None {no_accel} times)")
        raise SystemExit(1)

    print(f"{samples} samples  ({no_accel} empty reads)\n")
    print("ACCELEROMETER ranges:")
    best = []
    for i, name in enumerate("xyz"):
        span = accel_hi[i] - accel_lo[i]
        best.append((span, i))
        flag = "  <-- responds to your roll" if span > 0.5 else ""
        print(
            f"  accel {name} (index {i}): {accel_lo[i]:+6.2f} .. {accel_hi[i]:+6.2f}"
            f"   span {span:5.2f}{flag}"
        )

    print("\nGYROSCOPE ranges:")
    for i, name in enumerate("xyz"):
        if gyro_hi[i] < -8e8:
            print(f"  gyro {name} (index {i}): no data")
            continue
        span = gyro_hi[i] - gyro_lo[i]
        print(
            f"  gyro {name} (index {i}): {gyro_lo[i]:+8.2f} .. {gyro_hi[i]:+8.2f}"
            f"   span {span:6.2f}"
        )

    print()
    if gyro_peak < 0.05:
        print(f"GYRO: no signal (peak {gyro_peak:.3f}). Accelerometer-only.")
        print("      Not a problem -- gravity-vector roll needs no gyro.")
    else:
        print(f"GYRO: LIVE (peak magnitude {gyro_peak:.2f}).")

    if roll_hi > -8e8:
        print(f"FUSED ROLL: {roll_lo:+.1f} .. {roll_hi:+.1f} deg  (span {roll_hi - roll_lo:.1f})")
        roll_span = roll_hi - roll_lo
        if roll_span > 20:
            print("      -> use this. Run mac_sender.py WITHOUT --accel-only.")
        elif 1.0 < roll_span <= 20 and abs(roll_lo) < 3.2 and abs(roll_hi) < 3.2:
            # A big physical roll that reports a span of only a few units, all
            # within +/-pi, means the library is giving us RADIANS, not degrees.
            print("      -> WARNING: these look like RADIANS, not degrees.")
            print("         (small span, all values within +/-3.14)")
            print("         Tell Claude -- mac_sender.py needs a units fix.")
        else:
            print("      -> barely moved; prefer --accel-only with the axes below.")

    best.sort(reverse=True)
    lateral = best[0][1]
    vertical = best[1][1] if best[1][0] > 0.1 else (2 if lateral != 2 else 0)
    print("=" * 62)
    print("\nIf you need accelerometer-only mode, these are your flags:")
    print(f"    --accel-only --lateral {lateral} --vertical {vertical}")
    print("\nOtherwise just run mac_sender.py with no axis flags at all.")


if __name__ == "__main__":
    main()
