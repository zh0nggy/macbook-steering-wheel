"""STEP 2. Runs on the MAC, needs sudo. Reads tilt, sends steering over UDP.

    sudo python3 mac_sender.py --host 192.168.1.42

--host MUST be a LOCAL address: 192.168.x.x, 10.x.x.x, or 172.16-31.x.x.
Get it by running `ipconfig` ON THE WINDOWS PC and reading "IPv4 Address".
Do NOT use an address from a "what's my IP" website -- that is your building's
public router address, and packets sent there leave your network entirely.

By default this uses macimu's fused Mahony orientation (gyro + accelerometer),
which is more responsive than gravity alone. If imu_probe.py told you fused
roll doesn't move, fall back to:

    sudo python3 mac_sender.py --host <ip> --accel-only --lateral 0 --vertical 2

Add --throttle 0.3 (with AC's automatic gearbox on) to make the car drive
itself so steering is the only live input.
"""

import argparse
import math
import socket
import sys
import time

import imu_reader
import key_input
import protocol

GRAVITY_TOLERANCE = 0.35  # accel-only mode: reject samples this far from 1g
SHIFT_HOLD = 0.07         # seconds a gear key holds A / X (games poll ~every 16 ms)


def is_private(host):
    """Catch the most common setup mistake: using a public IP."""
    parts = host.split(".")
    if len(parts) != 4:
        return None  # hostname, not an IP -- can't judge
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if a == 192 and b == 168:
        return True
    if a == 10:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 127:
        return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True, help="LOCAL IP of the Windows PC")
    parser.add_argument("--port", type=int, default=protocol.DEFAULT_PORT)
    parser.add_argument(
        "--accel-only",
        action="store_true",
        help="ignore fused orientation, use gravity-vector roll",
    )
    parser.add_argument("--lateral", type=int, default=0, choices=[0, 1, 2])
    parser.add_argument("--vertical", type=int, default=2, choices=[0, 1, 2])
    parser.add_argument("--range", type=float, default=45.0, help="deg for full lock")
    parser.add_argument("--rate", type=float, default=100.0, help="packets/sec")
    parser.add_argument(
        "--lowpass",
        type=float,
        default=0.15,
        help="0..1, higher = smoother but laggier",
    )
    parser.add_argument("--invert", action="store_true")
    parser.add_argument(
        "--throttle",
        type=float,
        default=0.0,
        help="CONSTANT throttle 0..1, only used with --no-keys",
    )
    parser.add_argument(
        "--no-keys",
        action="store_true",
        help="disable keyboard capture (steering only, plus --throttle)",
    )
    # NOT caps_lock -- macOS treats it as a latching toggle, not a held key.
    parser.add_argument("--key-throttle", default="shift", help="left shift")
    parser.add_argument("--key-brake", default="enter", help="return")
    parser.add_argument("--key-gear-up", default="tab", help="-> pad A in AC")
    parser.add_argument("--key-gear-down", default="shift_r", help="right shift -> pad X")
    parser.add_argument(
        "--rise", type=float, default=0.35, help="sec for throttle/brake to reach full"
    )
    parser.add_argument(
        "--fall", type=float, default=0.18, help="sec for throttle/brake to release"
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    private = is_private(args.host)
    if private is False:
        raise SystemExit(
            f"\n{args.host} is NOT a local network address.\n\n"
            "That looks like a public internet IP. Steering packets sent there\n"
            "leave your network and go to a stranger's server.\n\n"
            "Run `ipconfig` ON THE WINDOWS PC and use the IPv4 Address line.\n"
            "It will start with 192.168. or 10. or 172.16-31.\n"
        )

    if args.accel_only and args.lateral == args.vertical:
        raise SystemExit("--lateral and --vertical must differ")

    imu = imu_reader.Imu()
    imu.start()
    time.sleep(0.3)

    use_fused = not args.accel_only and imu.orientation() is not None
    if args.accel_only:
        print("mode: accelerometer-only (gravity vector)")
    elif use_fused:
        print("mode: fused orientation (Mahony -- gyro + accel)")
    else:
        print("mode: fused orientation unavailable, falling back to accel-only")

    def raw_roll():
        """Returns (roll_degrees, status).

        status is "ok", "nodata" (the sensor had nothing buffered yet -- normal
        and harmless), or "rejected" (the sample was dominated by linear
        acceleration, so its tilt estimate is meaningless).

        These are reported separately on purpose: "nodata" says nothing about
        your technique, but a climbing "rejected" count means you are
        translating the laptop instead of rolling it in place.
        """
        if use_fused:
            orient = imu.orientation()
            return (None, "nodata") if orient is None else (orient[0], "ok")
        accel = imu.accel()
        if accel is None:
            return (None, "nodata")
        magnitude = math.sqrt(sum(v * v for v in accel))
        if abs(magnitude - 1.0) > GRAVITY_TOLERANCE:
            return (None, "rejected")
        roll = math.degrees(math.atan2(accel[args.lateral], accel[args.vertical]))
        return (roll, "ok")

    def wrap(deg):
        return (deg + 180.0) % 360.0 - 180.0

    # --- calibration: your current grip becomes centre ---
    print("\nHold the laptop at your NEUTRAL steering position.")
    input("Press Enter to calibrate centre... ")

    smoothed = None
    collected = []
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        value, _status = raw_roll()
        if value is not None:
            smoothed = value if smoothed is None else smoothed + wrap(
                value - smoothed
            ) * args.lowpass
            collected.append(smoothed)
        time.sleep(0.005)

    if not collected:
        imu.stop()
        raise SystemExit(
            "No usable samples during calibration. Run imu_probe.py and check "
            "the sensor is producing data."
        )

    centre = collected[-1]
    print(f"centre = {centre:+.1f} deg   full lock at +/-{args.range:.0f} deg")

    # --- keyboard: started AFTER calibration so the Enter above isn't captured ---
    keys = None
    throttle_ramp = key_input.Ramp(args.rise, args.fall)
    brake_ramp = key_input.Ramp(args.rise, args.fall)
    if args.no_keys:
        print(f"keys: disabled, constant throttle {args.throttle:.2f}\n")
    else:
        keys = key_input.Keys(
            throttle=args.key_throttle,
            brake=args.key_brake,
            gear_up=args.key_gear_up,
            gear_down=args.key_gear_down,
        )
        keys.start()
        print(
            f"keys: throttle={args.key_throttle} brake={args.key_brake} "
            f"up={args.key_gear_up} down={args.key_gear_down}"
        )
        print("      (captured globally -- they also type into the focused app)\n")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = (args.host, args.port)
    interval = 1.0 / args.rate
    seq = 0
    rejected = 0
    nodata = 0
    last_print = 0.0
    throttle = brake = 0.0
    gear_up = gear_down = 0
    last_counts = {"A": 0, "X": 0}
    press_until = {"A": 0.0, "X": 0.0}
    prev_loop = time.monotonic()

    print(f"sending to {args.host}:{args.port} at {args.rate:.0f} Hz -- ctrl-c to stop")
    try:
        while True:
            loop_start = time.monotonic()

            value, status = raw_roll()
            if value is None:
                if status == "rejected":
                    rejected += 1
                else:
                    nodata += 1
            else:
                # wrap the DELTA before smoothing so a wrap-around never
                # produces a full-lock spike
                smoothed = smoothed + wrap(value - smoothed) * args.lowpass

            offset = wrap(smoothed - centre)
            steer = protocol.clamp(offset / args.range, -1.0, 1.0)
            if args.invert:
                steer = -steer

            # Measure real elapsed time rather than assuming 1/rate, so the
            # pedal ramps stay correct even when the loop runs late.
            dt = loop_start - prev_loop
            prev_loop = loop_start

            if keys is None:
                throttle, brake = args.throttle, 0.0
            else:
                held_throttle, held_brake, gear_up, gear_down = keys.state()
                throttle = throttle_ramp.update(held_throttle, dt)
                brake = brake_ramp.update(held_brake, dt)
                # The wire format sends held buttons; turn each gear keypress
                # (a counter change) into a short press of A (up) / X (down).
                for name, count in (("A", gear_up), ("X", gear_down)):
                    if count != last_counts[name]:
                        last_counts[name] = count
                        press_until[name] = loop_start + SHIFT_HOLD
            buttons = 0
            for name, until in press_until.items():
                if loop_start < until:
                    buttons |= protocol.BUTTON_BIT[name]

            sock.sendto(
                protocol.pack(steer, throttle, brake, seq=seq, buttons=buttons),
                target,
            )
            seq += 1

            now = time.monotonic()
            if not args.quiet and now - last_print >= 0.2:
                pos = int((steer + 1.0) * 15)
                bar = "".join(
                    "|" if i == 15 else ("#" if i == pos else "-") for i in range(31)
                )
                sys.stdout.write(
                    f"\r[{bar}] steer={steer:+.3f} roll={offset:+6.1f}d "
                    f"sent={seq} rejected={rejected} nodata={nodata}  "
                )
                sys.stdout.flush()
                last_print = now

            slack = interval - (time.monotonic() - loop_start)
            if slack > 0:
                time.sleep(slack)
    except KeyboardInterrupt:
        print("\nstopping -- sending centred frames so the car doesn't stay locked")
        for _ in range(10):
            # Centred, pedals off, every button released.
            sock.sendto(protocol.pack(0.0, 0.0, 0.0, seq=seq), target)
            seq += 1
            time.sleep(0.01)
    finally:
        if keys is not None:
            keys.stop()
        imu.stop()
        sock.close()


if __name__ == "__main__":
    main()
