"""Tilt Wheel sender -- MAC. Same job as mac_sender.py, in a window.

Open it by double-clicking "Start Sender.command" (it asks for your password
once, because macimu needs root). Or from a terminal:

    sudo python3 sender_app.py

To try it without a MacBook (on Windows too), use a slider instead of the
motion sensor:

    python sender_app.py --demo

The Windows receiver app broadcasts a beacon, so its address shows up in the
list here automatically -- no ipconfig needed.

LATENCY: the sensor is polled every millisecond and a packet goes out as soon
as a new sample arrives (up to MAX_RATE per second), instead of on a fixed
100 Hz timer. Steering runs through a One Euro filter, which smooths jitter
when you hold still without adding lag when you turn. The receiver echoes
packets back, so the window shows the measured round-trip time.

KEYS ARE READ FROM THIS WINDOW, not globally like mac_sender.py. Keep it in
front while you drive. That avoids the Input Monitoring permission and stops
your pedal presses typing into some other app.
"""

import json
import math
import os
import socket
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox

import app_common
import controller_view
import protocol
from key_input import Ramp

# --demo: run without a MacBook (e.g. on Windows) using a slider as the sensor.
# Must happen before imu_reader is imported, because that imports macimu.
DEMO = "--demo" in sys.argv
if DEMO:
    import demo_imu
    demo_imu.install()

try:
    # mac_sender imports imu_reader -> macimu, so it lives inside the guard too.
    import imu_reader
    from mac_sender import GRAVITY_TOLERANCE, is_private
    IMPORT_ERROR = None
except Exception as exc:  # macimu missing, or not a Mac
    imu_reader = None
    IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


def wrap(deg):
    return (deg + 180.0) % 360.0 - 180.0


MAX_RATE = 250.0      # packets/sec ceiling when the sensor delivers fast
KEEPALIVE = 0.01      # always send at least every 10 ms (keys, failsafe)
POLL = 0.001          # how often to check the sensor for a new sample

# Accelerometer axes used only when the Mac has no fused orientation. If
# steering is wrong in that mode, `sudo python3 imu_probe.py` prints the right
# numbers for your laptop -- change them here.
FALLBACK_LATERAL = 0
FALLBACK_VERTICAL = 2


SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "sender_settings.json")


class WindowKeys:
    """Tracks held keys from Tk events and turns them into pad state.

    `bindings` is {target: keysym} from the controller picture. Targets are
    protocol.BUTTONS names plus "RT"/"LT" for the analog triggers. Keys are
    sent as HELD state; the receiver presses the pad button while held.
    """

    def __init__(self, root):
        self.held = set()
        self.bindings = {}
        self.intercept = None  # callable(keysym) -> True if it ate the key
        self._lock = threading.Lock()
        # Our own bind tag, put FIRST on every widget, so keys reach us before
        # Tk's built-ins. With plain bind_all, Tk's Tab focus-traversal binding
        # (also on "all") swallowed Tab before we saw it -- and Tab is a
        # default gear key. Returning "break" then stops the built-ins.
        self.root = root
        root.bind_class(self.TAG, "<KeyPress>", self._press)
        root.bind_class(self.TAG, "<KeyRelease>", self._release)
        self.install(root)
        # Losing focus means we stop hearing releases, so drop everything
        # rather than leave the throttle stuck on. FocusOut also fires when
        # focus just moves between widgets, so check the window really lost it.
        root.bind("<FocusOut>", lambda _e: root.after(20, self._check_focus))

    TAG = "TiltWheelKeys"

    def install(self, widget):
        """Put our tag first on `widget` and all its children. Call again after
        building the window, since widgets made later don't inherit it."""
        tags = widget.bindtags()
        if self.TAG not in tags:
            widget.bindtags((self.TAG,) + tags)
        for child in widget.winfo_children():
            self.install(child)

    def _check_focus(self):
        if self.root.focus_get() is None:
            self._clear()

    @staticmethod
    def _typing(event):
        return isinstance(event.widget, (tk.Entry, tk.Spinbox))

    @staticmethod
    def _name(event):
        sym = event.keysym
        return sym.lower() if len(sym) == 1 else sym

    def _press(self, event):
        if self._typing(event):
            return None  # let the IP box receive normal typing
        # While the controller picture is waiting for a key, the key binds
        # instead of driving the game.
        if self.intercept is not None and self.intercept(event.keysym):
            return "break"
        with self._lock:
            self.held.add(self._name(event))  # a set, so auto-repeat is harmless
        return "break"  # stop Tab moving focus, Space pressing buttons, etc.

    def _release(self, event):
        if self._typing(event):
            return None
        with self._lock:
            self.held.discard(self._name(event))
        return "break"

    def _clear(self):
        with self._lock:
            self.held.clear()

    def held_targets(self):
        """Set of bound targets whose key is held right now."""
        with self._lock:
            held = set(self.held)
        return {t for t, key in self.bindings.items() if key in held}

    def state(self):
        """(right_trigger_held, left_trigger_held, button_bitmask)."""
        targets = self.held_targets()
        mask = 0
        for name in targets:
            mask |= protocol.BUTTON_BIT.get(name, 0)
        return "RT" in targets, "LT" in targets, mask


class SenderEngine:
    """The mac_sender.py loop in a background thread.

    Unlike the script, calibration isn't a blocking prompt: the loop always
    tracks the smoothed roll, and "Calibrate" just copies it into `centre`.
    """

    def __init__(self, keys):
        self.keys = keys
        self.settings = {}
        self.target = None  # (ip, port) or None = not sending
        self.centre = None
        self.status = {"steer": 0.0, "throttle": 0.0, "brake": 0.0, "roll": 0.0,
                       "sent": 0, "rejected": 0, "nodata": 0, "mode": "starting"}
        self.error = None
        self._smoothed = None
        self._filter = app_common.OneEuroFilter()
        self.rtt = app_common.RollingStats(1.0)
        self.send_rate = app_common.RollingStats(1.0)
        self._stop = threading.Event()
        self._thread = None
        self._sock = app_common.low_latency_socket()
        self._sock.setblocking(False)

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def calibrate(self):
        self.centre = self._smoothed
        return self.centre

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self):
        imu = None
        try:
            imu = imu_reader.Imu()
            imu.start()
            time.sleep(0.3)
            self._loop(imu)
        except SystemExit as exc:  # imu_reader reports failures this way
            self.error = str(exc)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            if imu is not None:
                imu.stop()
            self._sock.close()

    def _raw_roll(self, imu, use_fused):
        if use_fused:
            orient = imu.orientation()
            return (None, "nodata") if orient is None else (orient[0], "ok")
        # Fallback for Macs without fused orientation: tilt from gravity alone.
        accel = imu.accel()
        if accel is None:
            return (None, "nodata")
        magnitude = math.sqrt(sum(v * v for v in accel))
        if abs(magnitude - 1.0) > GRAVITY_TOLERANCE:
            return (None, "rejected")
        return (math.degrees(math.atan2(accel[FALLBACK_LATERAL],
                                        accel[FALLBACK_VERTICAL])), "ok")

    def _loop(self, imu):
        fused_available = imu.orientation() is not None
        throttle_ramp = Ramp(0.35, 0.18)
        brake_ramp = Ramp(0.35, 0.18)
        seq = rejected = nodata = 0
        buttons = 0
        steer = offset = 0.0
        last_raw = None        # newest raw sample, to spot when a new one arrives
        unwrapped = None       # raw roll made continuous, so the filter never sees a jump
        last_sample_at = None
        prev_loop = last_send = time.monotonic()
        last_frame = None
        last_target = None
        st = self.status

        while not self._stop.is_set():
            loop_start = time.monotonic()
            cfg = self.settings
            st["mode"] = ("fused (gyro + accel)" if fused_available else
                          "gravity only (fused unavailable)")
            self._filter.min_cutoff = cfg["min_cutoff"]
            self._filter.beta = cfg["beta"]

            value, status = self._raw_roll(imu, fused_available)
            if value is None:
                if status == "rejected":
                    rejected += 1
                else:
                    nodata += 1
            else:
                # Run the filter on EVERY reading, repeats included. Updating only
                # on a changed value would freeze it mid-settle when the laptop
                # is held still and the sensor repeats itself.
                unwrapped = value if unwrapped is None else unwrapped + wrap(value - last_raw)
                last_raw = value
                dt = 0.0 if last_sample_at is None else loop_start - last_sample_at
                last_sample_at = loop_start
                self._smoothed = wrap(self._filter.update(unwrapped, dt))

                if self.centre is None:
                    self.centre = self._smoothed  # until the user calibrates properly
                offset = wrap(self._smoothed - self.centre)
                steer = protocol.clamp(offset / cfg["range"], -1.0, 1.0)
                if cfg["invert"]:
                    steer = -steer

            dt = loop_start - prev_loop
            prev_loop = loop_start
            held_rt, held_lt, buttons = self.keys.state()
            throttle = throttle_ramp.update(held_rt, dt)
            brake = brake_ramp.update(held_lt, dt)
            if cfg["throttle"] > 0.0:
                # Fixed throttle (cruise): never less than the slider value.
                throttle = max(throttle, cfg["throttle"])

            self._read_echoes(loop_start)

            target = self.target
            if target is None and last_target is not None:
                # Just pressed Stop: centre the car and release every button
                # on the way out.
                for _ in range(10):
                    self._send(last_target, 0.0, 0.0, 0.0, seq, 0)
                    seq += 1
                    time.sleep(0.01)
            # Send as soon as anything changes (capped at MAX_RATE), and on a
            # keepalive timer so the receiver failsafe stays happy while you
            # hold still or the sensor stalls. A button press always goes out
            # straight away rather than waiting for the rate cap.
            frame = (round(steer, 4), round(throttle, 3), round(brake, 3), buttons)
            since = loop_start - last_send
            buttons_changed = last_frame is None or buttons != last_frame[3]
            if target is not None and (buttons_changed
                                       or (frame != last_frame and since >= 1.0 / MAX_RATE)
                                       or since >= KEEPALIVE):
                self._send(target, steer, throttle, brake, seq, buttons)
                self.send_rate.add(1, loop_start)
                seq += 1
                last_send = loop_start
                last_frame = frame
            last_target = target

            st.update(steer=steer, throttle=throttle, brake=brake, roll=offset,
                      sent=seq, rejected=rejected, nodata=nodata)

            slack = POLL - (time.monotonic() - loop_start)
            if slack > 0:
                time.sleep(slack)

        if last_target is not None:
            for _ in range(10):
                self._send(last_target, 0.0, 0.0, 0.0, seq, 0)
                seq += 1
                time.sleep(0.01)

    def _read_echoes(self, now):
        """Collect the receiver's echoes (our ping) and answer its pings (its ping)."""
        while True:
            try:
                data, addr = self._sock.recvfrom(64)
            except OSError:  # BlockingIOError (nothing waiting), resets, etc.
                return
            pong = app_common.ping_to_pong(data)
            if pong is not None:
                try:
                    self._sock.sendto(pong, addr)
                except OSError:
                    pass
                continue
            sent_at = app_common.unpack_echo(data)
            if sent_at is not None and 0.0 <= now - sent_at < 2.0:
                self.rtt.add((now - sent_at) * 1000.0, now)

    def _send(self, target, steer, throttle, brake, seq, buttons):
        try:
            self._sock.sendto(protocol.pack(steer, throttle, brake, seq=seq,
                                            buttons=buttons), target)
        except OSError:
            pass  # network blip; the receiver's failsafe covers the gap


class SenderApp:
    def __init__(self, root):
        self.root = root
        root.title("Tilt Wheel - Sender (Mac)" + ("  [DEMO]" if DEMO else ""))
        root.resizable(False, False)

        self.keys = WindowKeys(root)
        self.listener = app_common.BeaconListener()
        self.listener.start()
        self.engine = None

        self.host = tk.StringVar()
        self.port = tk.IntVar(value=protocol.DEFAULT_PORT)
        self.range = tk.DoubleVar(value=45.0)
        self.min_cutoff = tk.DoubleVar(value=1.0)
        self.beta = tk.DoubleVar(value=0.3)
        self.invert = tk.BooleanVar(value=False)
        self.throttle = tk.DoubleVar(value=0.0)
        bindings = self.load_bindings()

        pad = {"padx": 12, "pady": 5}

        # Two columns: connection + steering on the left, controller on the
        # right, so the window still fits a laptop screen.
        left = tk.Frame(root)
        left.pack(side="left", fill="y", anchor="n")
        right = tk.Frame(root)
        right.pack(side="left", fill="y", anchor="n")
        outer = root
        root = left  # everything below packs into the left column by default

        if DEMO:
            demo = tk.LabelFrame(root, text="DEMO MODE: no motion sensor, drag to tilt",
                                 fg="#b06000")
            demo.pack(fill="x", **pad)
            self.fake_tilt = tk.DoubleVar(value=0.0)
            self.fake_tilt.trace_add("write", self._fake_tilt_changed)
            tk.Scale(demo, variable=self.fake_tilt, from_=-90, to=90, resolution=0.5,
                     orient="horizontal", length=330, label="Fake tilt (deg)").pack(
                         side="left", padx=4)
            tk.Button(demo, text="Centre", command=lambda: self.fake_tilt.set(0.0)).pack(
                side="left", padx=4)

        # --- where to send ---
        conn = tk.LabelFrame(root, text="Windows PC")
        conn.pack(fill="x", **pad)
        self.pc_list = tk.Listbox(conn, height=3, width=40, exportselection=False)
        self.pc_list.grid(row=0, column=0, columnspan=3, sticky="we", pady=(4, 2))
        self.pc_list.bind("<<ListboxSelect>>", self.pick_pc)
        tk.Label(conn, text="IP").grid(row=1, column=0, sticky="w")
        tk.Entry(conn, textvariable=self.host, width=16).grid(row=1, column=1, sticky="w")
        self.send_btn = tk.Button(conn, text="Start sending", width=14, command=self.toggle_send)
        self.send_btn.grid(row=1, column=2, sticky="e", pady=4)

        # --- live view ---
        live = tk.Frame(root)
        live.pack(fill="x", **pad)
        self.status = tk.Label(live, text="Starting sensor...", anchor="w", fg="#666")
        self.status.grid(row=0, column=0, columnspan=2, sticky="we")
        self.bars = {}
        for row, (key, label, color, centered) in enumerate([
            ("steer", "Steering", "#2b7de9", True),
            ("throttle", "Right trigger", "#2fa84f", False),
            ("brake", "Left trigger", "#d64545", False),
        ], start=1):
            tk.Label(live, text=label, width=12, anchor="w").grid(row=row, column=0, sticky="w")
            bar = app_common.Bar(live, color=color, centered=centered)
            bar.grid(row=row, column=1, pady=2)
            self.bars[key] = bar
        ping_row = tk.Frame(live)
        ping_row.grid(row=4, column=0, columnspan=2, sticky="we", pady=(4, 0))
        self.ping_label = tk.Label(ping_row, text="Ping: -- ms", anchor="w", fg="#888",
                                   font=("Helvetica", 14, "bold"))
        self.ping_label.pack(side="left")
        self.debug = app_common.DebugWindow(root, "Tilt Wheel - Sender debug", self._debug_rows)
        tk.Button(ping_row, text="Debug", command=self.debug.open).pack(side="right")
        tk.Button(live, text="Calibrate centre (hold neutral, then click)",
                  command=self.calibrate).grid(row=6, column=0, columnspan=2,
                                               sticky="we", pady=(4, 0))

        # --- tuning ---
        tuning = tk.LabelFrame(root, text="Steering (applies live)")
        tuning.pack(fill="x", **pad)
        app_common.labeled_scale(tuning, 0, "Range (deg)", self.range, 10, 90, 1)
        app_common.labeled_scale(tuning, 1, "Steadiness\n(lower = steadier)",
                                 self.min_cutoff, 0.1, 5.0, 0.1)
        app_common.labeled_scale(tuning, 2, "Turn response\n(higher = less lag)",
                                 self.beta, 0.0, 2.0, 0.05)
        tk.Checkbutton(tuning, text="Invert", variable=self.invert).grid(
            row=3, column=0, sticky="w")

        # --- controller: click a button, press a key ---
        pedals = tk.LabelFrame(right, text="Controls (this window must be in front)")
        # Stretch to the window's full height so both columns end on one line.
        pedals.pack(fill="both", expand=True, **pad)
        self.controller = controller_view.ControllerView(
            pedals, bindings, on_change=self._bindings_changed)
        self.controller.pack(padx=4, pady=(4, 0))
        self.keys.bindings = dict(bindings)
        self.keys.intercept = self.controller.handle_key
        cruise = tk.Frame(pedals)
        cruise.pack(fill="x", padx=4, pady=(controller_view.ControllerView.ROW_GAP, 4))
        app_common.labeled_scale(cruise, 0, "Fixed throttle\n(0 = off)", self.throttle, 0, 1, 0.05)

        root = outer
        root.protocol("WM_DELETE_WINDOW", self.close)
        # The left column sets the window height. Whatever the Controls box
        # has left over goes to the controller's grips, so the drawing fills it.
        # Sizes are only real once the window is on screen, so run it then.
        self._pedals = pedals
        root.after_idle(self._fill_controls)
        # Now every widget exists: route their keys through us first.
        self.keys.install(root)

        if IMPORT_ERROR:
            self.status.config(fg="#c03030", text="Sensor library failed to load")
            messagebox.showerror("Tilt Wheel", f"Could not load imu_reader / macimu:\n\n"
                                 f"{IMPORT_ERROR}\n\nRun: pip3 install macimu")
        else:
            self.engine = SenderEngine(self.keys)
            self.engine.settings = self.settings()
            self.engine.start()
        self.refresh()

    def settings(self):
        return {"range": max(1.0, self.range.get()),
                "min_cutoff": max(0.05, self.min_cutoff.get()), "beta": self.beta.get(),
                "invert": self.invert.get(), "throttle": self.throttle.get()}

    @staticmethod
    def load_bindings():
        """Key bindings from sender_settings.json, or the defaults."""
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as fh:
                saved = json.load(fh).get("bindings", {})
        except (OSError, ValueError, AttributeError):
            return dict(controller_view.DEFAULT_BINDINGS)
        valid = set(controller_view.TARGET_NAMES)
        bindings = {t: k for t, k in saved.items() if t in valid and isinstance(k, str)}
        return bindings or dict(controller_view.DEFAULT_BINDINGS)

    def _debug_rows(self):
        """Rows for the Debug window: (name, value, what it means)."""
        eng = self.engine
        if eng is None:
            return [("status", "no sensor", "the motion sensor isn't running")]
        st = eng.status
        rtt = eng.rtt.summary()
        return [
            ("mode", st["mode"].split(" (")[0], "how tilt is read: fused or gravity only"),
            ("roll", f"{st['roll']:+.1f} deg", "tilt from your calibrated centre"),
            ("steer", f"{st['steer']:+.3f}", "-1 full left .. +1 full right"),
            ("rate", f"{eng.send_rate.count()} Hz", "packets sent in the last second"),
            ("sent", f"{st['sent']}", "packets sent since the app opened"),
            ("ping avg", f"{rtt[0]:.1f} ms" if rtt else "--", "round trip to the PC"),
            ("ping max", f"{rtt[1]:.1f} ms" if rtt else "--", "worst round trip, last second"),
            ("rejected", f"{st['rejected']}", "readings skipped: laptop jolted, not tilted"),
            ("nodata", f"{st['nodata']}", "checks with no new reading yet (normal)"),
        ]

    def _fill_controls(self):
        """Stretch the controller so the Controls box has no empty band.

        The box is as tall as the left column; its contents are shorter. The
        difference goes to the drawing. Measured from the left column rather
        than the box, because the box itself grows when the drawing does.
        """
        self.root.update_idletasks()
        box = self._pedals
        left = box.master.master.winfo_children()[0]   # the left column frame
        target = left.winfo_reqheight()
        spare = target - box.master.winfo_reqheight()
        if spare > 0:
            canvas = self.controller.canvas
            leftover = self.controller.fit_height(canvas.winfo_reqheight() + spare)
            if leftover > 0:
                # Too much to stretch nicely: centre the drawing in the extra.
                self.controller.pack_configure(pady=(4 + leftover // 2, leftover - leftover // 2))

    def _bindings_changed(self, bindings):
        self.keys.bindings = dict(bindings)
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
                json.dump({"bindings": bindings}, fh, indent=2)
        except OSError:
            pass  # saving is a convenience; the binding still works this session

    def _fake_tilt_changed(self, *_):
        try:
            demo_imu.TILT["roll"] = self.fake_tilt.get()
        except tk.TclError:
            pass

    def pick_pc(self, _event=None):
        sel = self.pc_list.curselection()
        if sel:
            ip, port, _name = self.pcs[sel[0]]
            self.host.set(ip)
            self.port.set(port)

    def toggle_send(self):
        if self.engine is None:
            return
        if self.engine.target is not None:
            self.engine.target = None
            self.send_btn.config(text="Start sending")
            return
        host = self.host.get().strip()
        if not host:
            messagebox.showinfo("Tilt Wheel", "Pick your PC from the list, or type its IP.\n\n"
                                "If the list is empty, open the receiver app on Windows "
                                "and press Start.")
            return
        if is_private(host) is False:
            messagebox.showerror("Tilt Wheel", f"{host} is not a local network address.\n\n"
                                 "Use the address shown at the top of the Windows receiver "
                                 "app (192.168.x.x, 10.x.x.x or 172.16-31.x.x).")
            return
        self.engine.target = (host, int(self.port.get()))
        self.send_btn.config(text="Stop sending")

    def calibrate(self):
        if self.engine is None:
            return
        centre = self.engine.calibrate()
        if centre is None:
            messagebox.showwarning("Tilt Wheel", "No sensor data yet. Check the status line.")

    def refresh(self):
        # Discovered PCs
        self.pcs = self.listener.recent()
        labels = [f"{name}  ({ip})" for ip, _port, name in self.pcs]
        if list(self.pc_list.get(0, "end")) != labels:
            self.pc_list.delete(0, "end")
            for label in labels:
                self.pc_list.insert("end", label)
            if not labels:
                self.pc_list.insert("end", "Looking for the Windows receiver...")
        if len(self.pcs) == 1 and not self.host.get():
            self.host.set(self.pcs[0][0])
            self.port.set(self.pcs[0][1])

        # Light up the buttons whose keys are held, so you can see what's sent.
        self.controller.show_held(self.keys.held_targets())

        eng = self.engine
        if eng is not None:
            if eng.error:
                error = eng.error
                self.engine = None
                self.status.config(text="Sensor stopped", fg="#c03030")
                hint = ("\n\nmacimu needs root. Open the app with "
                        "'Start Sender.command' or `sudo python3 sender_app.py`."
                        if "root" in error.lower() or "permission" in error.lower() else "")
                messagebox.showerror("Tilt Wheel", error + hint)
            else:
                eng.settings = self.settings()
                st = eng.status
                for key, bar in self.bars.items():
                    bar.set(st[key])
                if eng.target is None:
                    self.status.config(text=f"Sensor: {st['mode']}  -  not sending", fg="#666")
                else:
                    self.status.config(fg="#1d7a35", text=(
                        f"Sending to {eng.target[0]}  -  {st['mode']}"))
                if eng.target is None:
                    self.ping_label.config(text="Ping: -- ms", fg="#888")
                else:
                    text, color = app_common.ping_display(eng.rtt)
                    self.ping_label.config(text=text, fg=color)
        self._timer = self.root.after(50, self.refresh)

    def close(self):
        if self.engine is not None:
            self.engine.target = None
            self.engine.stop()
        self.listener.stop()
        self.root.after_cancel(self._timer)
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    SenderApp(root)
    root.mainloop()
