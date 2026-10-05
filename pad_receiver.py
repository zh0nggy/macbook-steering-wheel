"""Runs on the WINDOWS PC. Turns UDP control frames into a virtual Xbox pad.

Setup:
    1. Install ViGEmBus from https://github.com/nefarius/ViGEmBus/releases
       (official releases only -- this is a kernel-mode driver)
    2. pip install vgamepad
    3. python pad_receiver.py
    4. Allow Python through Windows Firewall when prompted (inbound UDP)

Tuning knobs are --deadzone, --gamma and --smooth. Change these before you
start rewriting the filter on the Mac; most "it feels wrong" problems live here.
"""

import argparse
import socket
import time

import protocol

try:
    import vgamepad as vg
except ImportError:  # pragma: no cover - dev convenience on non-Windows machines
    vg = None


def shape(raw, deadzone, gamma):
    """Deadzone + response curve.

    Deadzone is rescaled, not just clipped, so you keep the full output range.
    gamma > 1 gives finer control near centre, which is what you want for a
    car; gamma = 1 is linear.
    """
    magnitude = abs(raw)
    if magnitude <= deadzone:
        return 0.0
    sign = 1.0 if raw > 0 else -1.0
    rescaled = (magnitude - deadzone) / (1.0 - deadzone)
    return sign * (rescaled ** gamma)


class ButtonPulse:
    """Presses a pad button for a fixed duration, without blocking.

    AC polls input at frame rate (~16 ms at 60 fps), so a button held for only
    one loop iteration (~2 ms) can be missed entirely. We hold it ~70 ms.

    Crucially this does NOT sleep -- the loop keeps sending steering while the
    button is down. Sleeping here would freeze the wheel every time you shift.
    """

    def __init__(self, pad, button, hold_seconds=0.07):
        self.pad = pad
        self.button = button
        self.hold = hold_seconds
        self.release_at = None
        self.last_count = None

    def check(self, count):
        """Call every loop with the current counter value from the packet."""
        if self.last_count is None:
            # First packet: adopt the sender's value without firing, so a
            # restart of the receiver mid-session doesn't trigger a phantom
            # shift.
            self.last_count = count
            return
        if count != self.last_count:
            self.last_count = count
            if self.pad is not None:
                self.pad.press_button(button=self.button)
            self.release_at = time.monotonic() + self.hold

    def maybe_release(self):
        if self.release_at is not None and time.monotonic() >= self.release_at:
            if self.pad is not None:
                self.pad.release_button(button=self.button)
            self.release_at = None


class Failsafe:
    """Centres the controls if the sensor stops sending.

    Without this, a crash or unplugged cable on the Mac leaves the car at
    whatever the last packet said -- usually full lock into a wall.
    """

    def __init__(self, timeout):
        self.timeout = timeout
        self.last_packet_at = None
        self.tripped = False

    def note_packet(self):
        self.last_packet_at = time.monotonic()
        if self.tripped:
            print("  link restored")
            self.tripped = False

    def is_stale(self):
        if self.last_packet_at is None:
            return True
        stale = (time.monotonic() - self.last_packet_at) > self.timeout
        if stale and not self.tripped:
            print("  !! no packets -- centring controls")
            self.tripped = True
        return stale


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=protocol.DEFAULT_PORT)
    parser.add_argument("--deadzone", type=float, default=0.05)
    parser.add_argument("--gamma", type=float, default=1.5)
    parser.add_argument(
        "--smooth",
        type=float,
        default=0.0,
        help="0.0 = none. 0.2-0.4 hides sensor noise but adds lag. Try 0 first.",
    )
    parser.add_argument("--invert", action="store_true", help="flip steering direction")
    parser.add_argument("--timeout", type=float, default=0.25, help="failsafe seconds")
    parser.add_argument(
        "--shift-hold",
        type=float,
        default=0.07,
        help="seconds to hold a gear button. Raise if shifts get missed.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print values, do not touch the pad"
    )
    args = parser.parse_args()

    if vg is None and not args.dry_run:
        raise SystemExit(
            "vgamepad not installed. Run 'pip install vgamepad' on Windows, "
            "or pass --dry-run to test the network path only."
        )

    pad = None if args.dry_run else vg.VX360Gamepad()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", args.port))
    sock.setblocking(False)

    # A and X to match the AC bindings: Gearshift Up = A, Gearshift Down = X.
    # In dry-run mode vg is None, so there is no button enum to reference.
    up_button = None if vg is None else vg.XUSB_BUTTON.XUSB_GAMEPAD_A
    down_button = None if vg is None else vg.XUSB_BUTTON.XUSB_GAMEPAD_X
    shift_up = ButtonPulse(pad, up_button, args.shift_hold)
    shift_down = ButtonPulse(pad, down_button, args.shift_hold)

    failsafe = Failsafe(args.timeout)
    steer = throttle = brake = 0.0
    received = dropped = 0
    shifts = 0
    last_seq = -1
    last_report = time.monotonic()

    print(f"listening on UDP {args.port}  (dry_run={args.dry_run})")
    print("ctrl-c to stop")
    try:
        while True:
            # Drain the socket and keep only the NEWEST frame. If we processed
            # every queued packet we would steer using stale positions and the
            # lag would grow without bound whenever we fall behind.
            newest = None
            while True:
                try:
                    data, _ = sock.recvfrom(protocol.PACKET_SIZE * 4)
                except BlockingIOError:
                    break
                frame = protocol.unpack(data)
                if frame is not None:
                    newest = frame

            if newest is not None:
                received += 1
                if last_seq >= 0 and newest["seq"] > last_seq + 1:
                    dropped += newest["seq"] - last_seq - 1
                last_seq = newest["seq"]
                failsafe.note_packet()

                target = -newest["steer"] if args.invert else newest["steer"]
                target = shape(target, args.deadzone, args.gamma)
                if args.smooth > 0.0:
                    steer += (target - steer) * (1.0 - args.smooth)
                else:
                    steer = target
                throttle = newest["throttle"]
                brake = newest["brake"]

                before = (shift_up.release_at, shift_down.release_at)
                shift_up.check(newest["gear_up"])
                shift_down.check(newest["gear_down"])
                if before != (shift_up.release_at, shift_down.release_at):
                    shifts += 1

            # Released on a timer, so shifting never blocks the steering loop.
            shift_up.maybe_release()
            shift_down.maybe_release()

            if failsafe.is_stale():
                steer = throttle = brake = 0.0

            if pad is not None:
                pad.left_joystick_float(x_value_float=steer, y_value_float=0.0)
                pad.right_trigger_float(value_float=throttle)
                pad.left_trigger_float(value_float=brake)
                pad.update()

            now = time.monotonic()
            if now - last_report >= 1.0:
                print(
                    f"  steer={steer:+.3f} thr={throttle:.2f} brk={brake:.2f} "
                    f"shifts={shifts} frames={received} dropped={dropped}"
                )
                last_report = now

            time.sleep(0.002)  # ~500 Hz output ceiling, well under the 20 ms budget
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        if pad is not None:
            pad.reset()
            pad.update()
        sock.close()


if __name__ == "__main__":
    main()
