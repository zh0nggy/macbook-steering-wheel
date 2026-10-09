"""Tilt Wheel receiver -- WINDOWS. Double-click to open (no terminal needed).

Same job as pad_receiver.py, in a window: receives UDP control frames and
drives a virtual Xbox pad via ViGEmBus. It also broadcasts a discovery beacon
so the Mac app finds this PC without anyone typing an IP address.

Works with any game that accepts an Xbox controller. Which Mac key presses
which pad button is set on the Mac (the controller picture in the sender app);
this side just mirrors it. Tuning is saved to receiver_settings.json next to
this file.

Needs ViGEmBus + `pip install vgamepad` for the real pad. Without them, tick
"Dry run" to test the network path only.

The .pyw extension makes Windows open it with pythonw (no console window).
Rename to .py if you want to see tracebacks while debugging.
"""

import json
import os
import socket
import threading
import time
import tkinter as tk
from tkinter import messagebox

import app_common
import mock_sender
import pad_mapping
import protocol
from pad_receiver import Failsafe, shape

try:
    import vgamepad as vg
except ImportError:
    vg = None

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "receiver_settings.json")


def resolve_button(name):
    """protocol button name -> vgamepad button value (or a placeholder in dry run)."""
    attr = pad_mapping.XUSB[name]
    return attr if vg is None else getattr(vg.XUSB_BUTTON, attr)


class ReceiverEngine:
    """The pad_receiver.py main loop, run in a background thread.

    The GUI never touches the socket or pad. It pushes settings in via
    `settings` and reads `status` back on a timer, so Tk stays on its own
    thread.
    """

    def __init__(self, port, dry_run, settings):
        self.port = port
        self.dry_run = dry_run
        self.settings = settings  # dict, replaced wholesale by the GUI
        self.status = {"steer": 0.0, "throttle": 0.0, "brake": 0.0,
                       "frames": 0, "dropped": 0, "presses": 0, "held": (),
                       "linked": False, "sender": None}
        self.error = None
        self.ping = app_common.RollingStats(1.0)  # round-trip ms to the Mac
        self._sender_addr = None
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self):
        pad = sock = beacon = None
        try:
            pad = None if self.dry_run else vg.VX360Gamepad()
            sock = app_common.low_latency_socket()
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", self.port))
            sock.setblocking(False)
            beacon = app_common.BeaconSender(self.port)
            self._loop(pad, sock, beacon)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            if pad is not None:
                pad.reset()
                pad.update()
            if sock is not None:
                sock.close()
            if beacon is not None:
                beacon.close()

    def _loop(self, pad, sock, beacon):
        buttons = pad_mapping.ButtonState(resolve_button)
        failsafe = Failsafe(self.settings["timeout"])

        steer = throttle = brake = 0.0
        mask = 0
        received = dropped = 0
        last_seq = -1
        next_ping = 0.0
        st = self.status

        while not self._stop.is_set():
            cfg = self.settings
            now = time.monotonic()
            beacon.tick()

            # Keep only the newest frame, exactly as pad_receiver.py does.
            newest = sender = None
            while True:
                try:
                    data, addr = sock.recvfrom(protocol.PACKET_SIZE * 4)
                except (BlockingIOError, ConnectionResetError):
                    break
                sent_at = app_common.unpack_pong(data)
                if sent_at is not None:
                    if 0.0 <= now - sent_at < 2.0:
                        self.ping.add((time.monotonic() - sent_at) * 1000.0)
                    continue
                frame = protocol.unpack(data)
                if frame is not None:
                    newest, sender = frame, addr
                    # Echo the sender's own timestamp so it can measure the
                    # round trip. Done per frame, before any processing, so
                    # the number reflects the network rather than this loop.
                    try:
                        sock.sendto(app_common.pack_echo(frame["timestamp"]), addr)
                    except OSError:
                        pass
            if sender is not None:
                self._sender_addr = sender
                sender = sender[0]

            # Our own ping to the Mac, ~10 per second, so this window can show
            # a ping too. Only while linked: there's nobody to ping otherwise.
            if (self._sender_addr is not None and not failsafe.is_stale()
                    and now >= next_ping):
                next_ping = now + 0.1
                try:
                    sock.sendto(app_common.pack_ping(time.monotonic()), self._sender_addr)
                except OSError:
                    pass

            if newest is not None:
                received += 1
                # A smaller seq means the sender restarted; don't count it as loss.
                if last_seq >= 0 and newest["seq"] > last_seq + 1:
                    dropped += newest["seq"] - last_seq - 1
                last_seq = newest["seq"]
                failsafe.note_packet()

                target = -newest["steer"] if cfg["invert"] else newest["steer"]
                target = shape(target, cfg["deadzone"], cfg["gamma"])
                if cfg["smooth"] > 0.0:
                    steer += (target - steer) * (1.0 - cfg["smooth"])
                else:
                    steer = target
                throttle = newest["right_trigger"]
                brake = newest["left_trigger"]
                mask = newest["buttons"]
                st["sender"] = sender

            stale = failsafe.is_stale()
            if stale:
                # Release everything, so a lost link can't leave a button held.
                steer = throttle = brake = 0.0
                mask = 0
            buttons.update(pad, mask)

            if pad is not None:
                pad_mapping.apply(pad, steer, throttle, brake)
                pad.update()

            st.update(steer=steer, throttle=throttle, brake=brake, frames=received,
                      dropped=dropped, presses=buttons.presses,
                      held=tuple(sorted(buttons.held)), linked=not stale)
            time.sleep(0.001)  # ~1.5 ms in practice; frames wait at most that long


class FakeSender:
    """Built-in mock_sender.py: sweeps steering into this same PC (127.0.0.1)."""

    def __init__(self, port):
        self.port = port
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._stop.set()

    def _run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        start = time.monotonic()
        seq = 0
        try:
            while not self._stop.is_set():
                steer = mock_sender.steering_for("sweep", time.monotonic() - start, 4.0)
                sock.sendto(protocol.pack(steer, seq=seq), ("127.0.0.1", self.port))
                seq += 1
                time.sleep(0.01)
        finally:
            sock.close()


class ReceiverApp:
    def __init__(self, root):
        self.root = root
        self.engine = None
        self.fake = None
        root.title("Tilt Wheel - Receiver (Windows)")
        root.resizable(False, False)

        self.deadzone = tk.DoubleVar(value=0.05)
        self.gamma = tk.DoubleVar(value=1.5)
        self.smooth = tk.DoubleVar(value=0.0)
        self.invert = tk.BooleanVar(value=False)
        self.dry_run = tk.BooleanVar(value=vg is None)
        self.port = tk.IntVar(value=protocol.DEFAULT_PORT)
        self.load_settings()

        pad = {"padx": 12, "pady": 6}

        top = tk.Frame(root)
        top.pack(fill="x", **pad)
        tk.Label(top, text=f"This PC: {app_common.local_ip()}",
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        tk.Label(top, text="  port").pack(side="left")
        tk.Entry(top, textvariable=self.port, width=6).pack(side="left")

        controls = tk.Frame(root)
        controls.pack(fill="x", **pad)
        self.start_btn = tk.Button(controls, text="Start", width=10, command=self.toggle)
        self.start_btn.pack(side="left")
        tk.Checkbutton(controls, text="Dry run (no virtual pad)",
                       variable=self.dry_run).pack(side="left", padx=8)
        self.fake_btn = tk.Button(controls, text="Test: fake sweep", command=self.toggle_fake)
        self.fake_btn.pack(side="right")

        self.status = tk.Label(root, text="Stopped", anchor="w", fg=app_common.muted(self.root))
        self.status.pack(fill="x", **pad)

        meters = tk.Frame(root)
        meters.pack(fill="x", **pad)
        self.bars = {}
        for row, (key, label, color, centered) in enumerate([
            ("steer", "Steering", "#2b7de9", True),
            ("throttle", "Right trigger", "#2fa84f", False),
            ("brake", "Left trigger", "#d64545", False),
        ]):
            tk.Label(meters, text=label, width=12, anchor="w").grid(row=row, column=0, sticky="w")
            bar = app_common.Bar(meters, color=color, centered=centered, width=300)
            bar.grid(row=row, column=1, pady=2)
            self.bars[key] = bar
        ping_row = tk.Frame(root)
        ping_row.pack(fill="x", padx=12, pady=6)
        self.ping_label = tk.Label(ping_row, text="Ping: -- ms", anchor="w", fg=app_common.muted(self.root),
                                   font=("Segoe UI", 11, "bold"))
        self.ping_label.pack(side="left")
        self.debug = app_common.DebugWindow(root, "Tilt Wheel - Receiver debug", self._debug_rows)
        tk.Button(ping_row, text="Debug", command=self.debug.open).pack(side="right")

        tuning = tk.LabelFrame(root, text="Tuning (applies live)")
        tuning.pack(fill="x", **pad)
        app_common.labeled_scale(tuning, 0, "Deadzone", self.deadzone, 0.0, 0.3, 0.01)
        app_common.labeled_scale(tuning, 1, "Gamma", self.gamma, 1.0, 3.0, 0.05)
        app_common.labeled_scale(tuning, 2, "Smoothing", self.smooth, 0.0, 0.9, 0.05)
        tk.Checkbutton(tuning, text="Invert steering", variable=self.invert).grid(
            row=3, column=0, columnspan=2, sticky="w")

        tk.Label(root, anchor="w", justify="left", fg=app_common.muted(root), wraplength=380, text=(
            "Works with any game that supports an Xbox controller. Start this "
            "before launching the game (most only look for controllers at "
            "startup). Choose which Mac key presses which button in the Mac "
            "app's controller picture. Check the pad in Win+R > joy.cpl."
        )).pack(fill="x", **pad)

        if vg is None:
            self.status.config(text="vgamepad not installed: dry run only "
                                    "(pip install vgamepad + ViGEmBus)", fg="#b06000")

        root.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()

    def settings(self):
        return {"deadzone": self.deadzone.get(), "gamma": self.gamma.get(),
                "smooth": self.smooth.get(), "invert": self.invert.get(),
                "timeout": 0.25}

    def _debug_rows(self):
        """Rows for the Debug window: (name, value, what it means)."""
        eng = self.engine
        if eng is None:
            return [("status", "stopped", "press Start to receive")]
        st = eng.status
        frames, dropped = st["frames"], st["dropped"]
        total = frames + dropped
        loss = f"{100 * dropped / total:.1f}%" if total else "--"
        rtt = eng.ping.summary()
        return [
            ("linked", "yes" if st["linked"] else "no", "receiving packets right now"),
            ("from", st["sender"] or "--", "the Mac's address"),
            ("steer", f"{st['steer']:+.3f}", "after deadzone / gamma, sent to the pad"),
            ("held", " ".join(st["held"]) or "-", "pad buttons held right now"),
            ("frames", f"{frames}", "updates applied from the Mac"),
            ("dropped", f"{dropped}", "packets lost or skipped as stale"),
            ("loss", loss, "dropped / total. Fine under ~10%"),
            ("ping avg", f"{rtt[0]:.1f} ms" if rtt else "--", "round trip to the Mac"),
            ("ping max", f"{rtt[1]:.1f} ms" if rtt else "--", "worst round trip, last second"),
        ]

    def load_settings(self):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return  # first run, or a broken file: keep defaults
        for key, var in (("deadzone", self.deadzone), ("gamma", self.gamma),
                         ("smooth", self.smooth), ("invert", self.invert),
                         ("port", self.port)):
            if key in data:
                try:
                    var.set(data[key])
                except tk.TclError:
                    pass

    def save_settings(self):
        try:
            data = {"deadzone": self.deadzone.get(), "gamma": self.gamma.get(),
                    "smooth": self.smooth.get(), "invert": self.invert.get(),
                    "port": int(self.port.get())}
            with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except (OSError, ValueError, tk.TclError):
            pass  # saving is a convenience; never block closing the app

    def toggle(self):
        if self.engine is not None:
            self.stop_engine()
            return
        if vg is None and not self.dry_run.get():
            messagebox.showerror("Tilt Wheel", "vgamepad isn't installed, so only dry run "
                                 "works.\n\nInstall ViGEmBus, then: pip install vgamepad")
            self.dry_run.set(True)
            return
        try:
            port = int(self.port.get())
        except (tk.TclError, ValueError):
            messagebox.showerror("Tilt Wheel", "Port must be a number.")
            return
        self.engine = ReceiverEngine(port, self.dry_run.get(), self.settings())
        self.engine.start()
        self.start_btn.config(text="Stop")

    def stop_engine(self):
        if self.fake is not None:
            self.toggle_fake()
        self.engine.stop()
        self.engine = None
        self.start_btn.config(text="Start")
        self.ping_label.config(text="Ping: -- ms", fg=app_common.muted(self.root))
        for bar in self.bars.values():
            bar.set(0.0)

    def toggle_fake(self):
        if self.fake is not None:
            self.fake.stop()
            self.fake = None
            self.fake_btn.config(text="Test: fake sweep")
            return
        if self.engine is None:
            self.toggle()
            if self.engine is None:
                return
        self.fake = FakeSender(self.engine.port)
        self.fake.start()
        self.fake_btn.config(text="Stop fake sweep")

    def refresh(self):
        eng = self.engine
        if eng is not None:
            if eng.error:
                error = eng.error
                self.stop_engine()
                hint = ""
                if "10048" in error or "in use" in error.lower():
                    hint = "\n\nAnother receiver (or pad_receiver.py) is already using this port."
                elif "VIGEM" in error.upper() or "bus" in error.lower():
                    hint = "\n\nViGEmBus doesn't look installed. Reboot after installing it."
                messagebox.showerror("Tilt Wheel", error + hint)
            else:
                eng.settings = self.settings()
                st = eng.status
                for key, bar in self.bars.items():
                    bar.set(st[key])
                if st["linked"]:
                    source = "fake sweep" if self.fake else st["sender"]
                    self.status.config(text=f"Receiving from {source}", fg="#1d7a35")
                else:
                    self.status.config(
                        text="Waiting for the Mac... (controls centred)", fg="#b06000")
                text, color = app_common.ping_display(eng.ping)
                self.ping_label.config(text=text, fg=color)
        elif vg is not None:
            self.status.config(text="Stopped", fg=app_common.muted(self.root))
        self._timer = self.root.after(50, self.refresh)

    def close(self):
        if self.engine is not None:
            self.stop_engine()
        self.save_settings()
        self.root.after_cancel(self._timer)
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    ReceiverApp(root)
    root.mainloop()
