"""Tilt Wheel receiver -- WINDOWS. Double-click to open (no terminal needed).

Same job as pad_receiver.py, in a window: receives UDP control frames and
drives a virtual Xbox pad via ViGEmBus. It also broadcasts a discovery beacon
so the Mac app finds this PC without anyone typing an IP address.

Works with any game that accepts an Xbox controller. Pick a preset (or
Custom) under "Game mapping" to choose which stick/trigger steering and pedals
drive and which pad buttons the Mac's two shift keys press. Settings are saved
to receiver_settings.json next to this file.

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
    """Mapping display name -> vgamepad button value (or a placeholder in dry run)."""
    attr = pad_mapping.BUTTONS.get(name)
    if attr is None:
        return None
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
                       "frames": 0, "dropped": 0, "shifts": 0,
                       "linked": False, "sender": None}
        self.error = None
        self.test_presses = []  # GUI appends "button_1"/"button_2" to press once
        self.ping = app_common.RollingStats(1.0)  # round-trip ms to the Mac
        self._sender_addr = None
        self._beacon = None
        self._stop = threading.Event()
        self._thread = None

    def addresses(self):
        """[(adapter, ip)] this PC is announcing itself on (WiFi, USB-C, ...)."""
        beacon = self._beacon
        return list(beacon.addresses) if beacon is not None else []

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
            beacon = self._beacon = app_common.BeaconSender(self.port)
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
                self._beacon = None
                beacon.close()

    def _loop(self, pad, sock, beacon):
        hold = self.settings["shift_hold"]
        # Counter fields in the packet -> the mapping role that decides the button.
        pulses = {"gear_up": ("button_1", pad_mapping.Pulse(hold)),
                  "gear_down": ("button_2", pad_mapping.Pulse(hold))}
        failsafe = Failsafe(self.settings["timeout"])

        steer = throttle = brake = 0.0
        received = dropped = shifts = 0
        last_seq = -1
        next_ping = 0.0
        st = self.status

        while not self._stop.is_set():
            cfg = self.settings
            mapping = cfg["mapping"]
            now = time.monotonic()
            beacon.tick()

            while self.test_presses:
                role = self.test_presses.pop(0)
                field = "gear_up" if role == "button_1" else "gear_down"
                pulses[field][1].fire(pad, resolve_button(mapping[role]), now)

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
                throttle = newest["throttle"]
                brake = newest["brake"]

                for field, (role, pulse) in pulses.items():
                    if pulse.check(newest[field], pad, resolve_button(mapping[role]), now):
                        shifts += 1
                st["sender"] = sender

            # Released on a timer, so pressing never blocks the steering loop.
            for _role, pulse in pulses.values():
                pulse.maybe_release(pad, now)

            stale = failsafe.is_stale()
            if stale:
                steer = throttle = brake = 0.0

            if pad is not None:
                pad_mapping.apply(pad, mapping, steer, throttle, brake)
                pad.update()

            st.update(steer=steer, throttle=throttle, brake=brake, frames=received,
                      dropped=dropped, shifts=shifts, linked=not stale)
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
        self.preset = tk.StringVar(value=pad_mapping.DEFAULT_PRESET)
        self.map_vars = {role: tk.StringVar(value=value) for role, value
                         in pad_mapping.PRESETS[pad_mapping.DEFAULT_PRESET].items()}
        self._applying_preset = False
        self.load_settings()

        pad = {"padx": 12, "pady": 6}

        top = tk.Frame(root)
        top.pack(fill="x", **pad)
        self.ip_label = tk.Label(top, text=self.address_text(app_common.interfaces()),
                                 font=("Segoe UI", 11, "bold"), justify="left", anchor="w")
        self.ip_label.pack(side="left")
        port_box = tk.Frame(top)
        port_box.pack(side="right", anchor="n")
        tk.Label(port_box, text="port").pack(side="left")
        tk.Entry(port_box, textvariable=self.port, width=6).pack(side="left")

        controls = tk.Frame(root)
        controls.pack(fill="x", **pad)
        self.start_btn = tk.Button(controls, text="Start", width=10, command=self.toggle)
        self.start_btn.pack(side="left")
        tk.Checkbutton(controls, text="Dry run (no virtual pad)",
                       variable=self.dry_run).pack(side="left", padx=8)
        self.fake_btn = tk.Button(controls, text="Test: fake sweep", command=self.toggle_fake)
        self.fake_btn.pack(side="right")

        self.status = tk.Label(root, text="Stopped", anchor="w", fg="#666")
        self.status.pack(fill="x", **pad)

        meters = tk.Frame(root)
        meters.pack(fill="x", **pad)
        self.bars = {}
        for row, (key, label, color, centered) in enumerate([
            ("steer", "Steering", "#2b7de9", True),
            ("throttle", "Throttle", "#2fa84f", False),
            ("brake", "Brake", "#d64545", False),
        ]):
            tk.Label(meters, text=label, width=9, anchor="w").grid(row=row, column=0, sticky="w")
            bar = app_common.Bar(meters, color=color, centered=centered)
            bar.grid(row=row, column=1, pady=2)
            self.bars[key] = bar
        self.counters = tk.Label(root, text="", anchor="w", font=("Consolas", 9))
        self.counters.pack(fill="x", padx=12, pady=(6, 0))
        self.ping_label = tk.Label(root, text="Ping: -- ms", anchor="w", fg="#888",
                                   font=("Segoe UI", 11, "bold"))
        self.ping_label.pack(fill="x", padx=12, pady=(0, 6))

        tuning = tk.LabelFrame(root, text="Tuning (applies live)")
        tuning.pack(fill="x", **pad)
        app_common.labeled_scale(tuning, 0, "Deadzone", self.deadzone, 0.0, 0.3, 0.01)
        app_common.labeled_scale(tuning, 1, "Gamma", self.gamma, 1.0, 3.0, 0.05)
        app_common.labeled_scale(tuning, 2, "Smoothing", self.smooth, 0.0, 0.9, 0.05)
        tk.Checkbutton(tuning, text="Invert steering", variable=self.invert).grid(
            row=3, column=0, columnspan=2, sticky="w")

        mapping = tk.LabelFrame(root, text="Game mapping (Xbox 360 pad)")
        mapping.pack(fill="x", **pad)
        tk.Label(mapping, text="Preset", anchor="w").grid(row=0, column=0, sticky="w")
        tk.OptionMenu(mapping, self.preset, *pad_mapping.PRESETS, pad_mapping.CUSTOM,
                      command=self.apply_preset).grid(row=0, column=1, columnspan=2,
                                                      sticky="we")
        rows = [
            ("steer", "Steering", pad_mapping.STEER_TARGETS),
            ("throttle", "Throttle", pad_mapping.PEDAL_TARGETS),
            ("brake", "Brake", pad_mapping.PEDAL_TARGETS),
            ("button_1", "Button 1\n(Mac gear up)", pad_mapping.BUTTONS),
            ("button_2", "Button 2\n(Mac gear down)", pad_mapping.BUTTONS),
        ]
        for row, (role, label, choices) in enumerate(rows, start=1):
            tk.Label(mapping, text=label, anchor="w", justify="left").grid(
                row=row, column=0, sticky="w")
            tk.OptionMenu(mapping, self.map_vars[role], *choices).grid(
                row=row, column=1, sticky="we")
            if role.startswith("button"):
                tk.Button(mapping, text="Test", command=lambda r=role: self.test_press(r)
                          ).grid(row=row, column=2, padx=(6, 0))
            self.map_vars[role].trace_add("write", self.mapping_changed)
        mapping.columnconfigure(1, weight=1)

        tk.Label(root, anchor="w", justify="left", fg="#666", wraplength=380, text=(
            "Works with any game that supports an Xbox controller. Start this "
            "before launching the game (most only look for controllers at "
            "startup), then bind controls in the game to match the mapping. "
            "'Test' presses a button once, handy for in-game rebinding. "
            "Check the pad in Win+R > joy.cpl."
        )).pack(fill="x", **pad)

        if vg is None:
            self.status.config(text="vgamepad not installed: dry run only "
                                    "(pip install vgamepad + ViGEmBus)", fg="#b06000")

        root.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()

    @staticmethod
    def address_text(found):
        """Header text: one line per network, cable first, e.g.
        'USB-C cable: 169.254.37.114' / 'WiFi / LAN: 10.39.44.93'."""
        ips = sorted({entry[1] for entry in found},
                     key=lambda ip: (not app_common.is_link_local(ip), ip))
        if not ips:
            return "This PC: no network"
        return "\n".join(f"{app_common.link_kind(ip)}: {ip}" for ip in ips)

    def mapping(self):
        return {role: var.get() for role, var in self.map_vars.items()}

    def settings(self):
        return {"deadzone": self.deadzone.get(), "gamma": self.gamma.get(),
                "smooth": self.smooth.get(), "invert": self.invert.get(),
                "timeout": 0.25, "shift_hold": 0.07, "mapping": self.mapping()}

    def apply_preset(self, name):
        if name not in pad_mapping.PRESETS:
            return  # "Custom": keep whatever is selected now
        self._applying_preset = True
        for role, value in pad_mapping.PRESETS[name].items():
            self.map_vars[role].set(value)
        self._applying_preset = False

    def mapping_changed(self, *_):
        if not self._applying_preset:
            self.preset.set(pad_mapping.preset_for(self.mapping()))

    def test_press(self, role):
        if self.engine is None:
            messagebox.showinfo("Tilt Wheel", "Press Start first so the virtual pad exists.")
            return
        self.engine.test_presses.append(role)

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
        mapping = pad_mapping.sanitize(data.get("mapping", {}))
        for role, value in mapping.items():
            self.map_vars[role].set(value)
        self.preset.set(pad_mapping.preset_for(mapping))

    def save_settings(self):
        try:
            data = {"deadzone": self.deadzone.get(), "gamma": self.gamma.get(),
                    "smooth": self.smooth.get(), "invert": self.invert.get(),
                    "port": int(self.port.get()), "mapping": self.mapping()}
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
        self.ping_label.config(text="Ping: -- ms", fg="#888")
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
                # Picks up a USB-C cable being plugged in (the beacon rescans).
                text = self.address_text(eng.addresses())
                if text != self.ip_label.cget("text"):
                    self.ip_label.config(text=text)
                st = eng.status
                for key, bar in self.bars.items():
                    bar.set(st[key])
                if st["linked"]:
                    source = "fake sweep" if self.fake else st["sender"]
                    self.status.config(text=f"Receiving from {source}", fg="#1d7a35")
                else:
                    self.status.config(
                        text="Waiting for the Mac... (controls centred)", fg="#b06000")
                self.counters.config(text=(
                    f"steer={st['steer']:+.3f}  frames={st['frames']}  "
                    f"dropped={st['dropped']}  shifts={st['shifts']}"))
                text, color = app_common.ping_display(eng.ping)
                self.ping_label.config(text=text, fg=color)
        elif vg is not None:
            self.status.config(text="Stopped", fg="#666")
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
