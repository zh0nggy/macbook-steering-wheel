"""Tilt Wheel sender -- MAC. Same job as mac_sender.py, in a window.

Open it by double-clicking "Start Sender.command" (it asks for your password
once, because macimu needs root). Or from a terminal:

    sudo python3 sender_app.py

The Windows receiver app broadcasts a beacon, so its address shows up in the
list here automatically -- no ipconfig needed.

KEYS ARE READ FROM THIS WINDOW, not globally like mac_sender.py. Keep it in
front while you drive. That avoids the Input Monitoring permission and stops
your pedal presses typing into some other app.
"""

import math
import socket
import threading
import time
import tkinter as tk
from tkinter import messagebox

import app_common
import protocol
from key_input import Ramp

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


# Key choices offered in the window -> Tk keysym. Tk names keys differently
# from pynput, and caps lock is left out for the same reason as key_input.py:
# macOS latches it instead of reporting hold.
KEY_CHOICES = {
    "Left Shift": "Shift_L", "Right Shift": "Shift_R", "Return": "Return",
    "Tab": "Tab", "Space": "space", "Up": "Up", "Down": "Down", "Left": "Left",
    "Right": "Right", "Z": "z", "X": "x", "A": "a", "S": "s", "Q": "q", "W": "w",
}


class WindowKeys:
    """Tracks held keys from Tk events. Same state() contract as key_input.Keys."""

    def __init__(self, root):
        self.held = set()
        self.gear_up_count = 0
        self.gear_down_count = 0
        self.bindings = {}
        self._lock = threading.Lock()
        root.bind_all("<KeyPress>", self._press)
        root.bind_all("<KeyRelease>", self._release)
        # Losing focus means we stop hearing releases, so drop everything
        # rather than leave the throttle stuck on. FocusOut also fires when
        # focus just moves between widgets, so check the window really lost it.
        self.root = root
        root.bind("<FocusOut>", lambda _e: root.after(20, self._check_focus))

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
        name = self._name(event)
        with self._lock:
            if name not in self.held:  # ignore auto-repeat: one press = one shift
                self.held.add(name)
                if name == self.bindings.get("gear_up"):
                    self.gear_up_count = (self.gear_up_count + 1) & 0xFF
                elif name == self.bindings.get("gear_down"):
                    self.gear_down_count = (self.gear_down_count + 1) & 0xFF
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

    def state(self):
        with self._lock:
            return (self.bindings.get("throttle") in self.held,
                    self.bindings.get("brake") in self.held,
                    self.gear_up_count, self.gear_down_count)


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
        self._stop = threading.Event()
        self._thread = None
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

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

    def _raw_roll(self, imu, use_fused, lateral, vertical):
        if use_fused:
            orient = imu.orientation()
            return (None, "nodata") if orient is None else (orient[0], "ok")
        accel = imu.accel()
        if accel is None:
            return (None, "nodata")
        magnitude = math.sqrt(sum(v * v for v in accel))
        if abs(magnitude - 1.0) > GRAVITY_TOLERANCE:
            return (None, "rejected")
        return (math.degrees(math.atan2(accel[lateral], accel[vertical])), "ok")

    def _loop(self, imu):
        fused_available = imu.orientation() is not None
        throttle_ramp = Ramp(0.35, 0.18)
        brake_ramp = Ramp(0.35, 0.18)
        seq = rejected = nodata = 0
        gear_up = gear_down = 0
        prev_loop = time.monotonic()
        last_target = None
        st = self.status

        while not self._stop.is_set():
            loop_start = time.monotonic()
            cfg = self.settings
            use_fused = fused_available and not cfg["accel_only"]
            st["mode"] = ("fused (gyro + accel)" if use_fused else
                          "accel-only" if cfg["accel_only"] else
                          "accel-only (fused unavailable)")

            value, status = self._raw_roll(imu, use_fused, cfg["lateral"], cfg["vertical"])
            if value is None:
                if status == "rejected":
                    rejected += 1
                else:
                    nodata += 1
            elif self._smoothed is None:
                self._smoothed = value
            else:
                # wrap the DELTA before smoothing so a wrap-around never spikes
                self._smoothed += wrap(value - self._smoothed) * cfg["lowpass"]

            if self._smoothed is not None and self.centre is None:
                self.centre = self._smoothed  # until the user calibrates properly

            offset = 0.0 if self.centre is None else wrap(self._smoothed - self.centre)
            steer = protocol.clamp(offset / cfg["range"], -1.0, 1.0)
            if cfg["invert"]:
                steer = -steer

            dt = loop_start - prev_loop
            prev_loop = loop_start
            if cfg["use_keys"]:
                held_t, held_b, gear_up, gear_down = self.keys.state()
                throttle = throttle_ramp.update(held_t, dt)
                brake = brake_ramp.update(held_b, dt)
            else:
                throttle, brake = cfg["throttle"], 0.0

            target = self.target
            if target is None and last_target is not None:
                # Just pressed Stop: centre the car on the way out, keeping the
                # gear counters so the receiver doesn't fire a phantom shift.
                for _ in range(10):
                    self._send(last_target, 0.0, 0.0, 0.0, seq, gear_up, gear_down)
                    seq += 1
                    time.sleep(0.01)
            if target is not None:
                self._send(target, steer, throttle, brake, seq, gear_up, gear_down)
                seq += 1
            last_target = target

            st.update(steer=steer, throttle=throttle, brake=brake, roll=offset,
                      sent=seq, rejected=rejected, nodata=nodata)

            slack = 1.0 / cfg["rate"] - (time.monotonic() - loop_start)
            if slack > 0:
                time.sleep(slack)

        if last_target is not None:
            for _ in range(10):
                self._send(last_target, 0.0, 0.0, 0.0, seq, gear_up, gear_down)
                seq += 1
                time.sleep(0.01)

    def _send(self, target, steer, throttle, brake, seq, gear_up, gear_down):
        try:
            self._sock.sendto(protocol.pack(steer, throttle, brake, seq=seq,
                                            gear_up=gear_up, gear_down=gear_down), target)
        except OSError:
            pass  # network blip; the receiver's failsafe covers the gap


class SenderApp:
    def __init__(self, root):
        self.root = root
        root.title("Tilt Wheel - Sender (Mac)")
        root.resizable(False, False)

        self.keys = WindowKeys(root)
        self.listener = app_common.BeaconListener()
        self.listener.start()
        self.engine = None

        self.host = tk.StringVar()
        self.port = tk.IntVar(value=protocol.DEFAULT_PORT)
        self.range = tk.DoubleVar(value=45.0)
        self.lowpass = tk.DoubleVar(value=0.15)
        self.invert = tk.BooleanVar(value=False)
        self.use_keys = tk.BooleanVar(value=True)
        self.throttle = tk.DoubleVar(value=0.0)
        self.accel_only = tk.BooleanVar(value=False)
        self.lateral = tk.IntVar(value=0)
        self.vertical = tk.IntVar(value=2)
        self.key_vars = {
            "throttle": tk.StringVar(value="Left Shift"),
            "brake": tk.StringVar(value="Return"),
            "gear_up": tk.StringVar(value="Tab"),
            "gear_down": tk.StringVar(value="Right Shift"),
        }

        pad = {"padx": 12, "pady": 5}

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
            ("throttle", "Throttle", "#2fa84f", False),
            ("brake", "Brake", "#d64545", False),
        ], start=1):
            tk.Label(live, text=label, width=9, anchor="w").grid(row=row, column=0, sticky="w")
            bar = app_common.Bar(live, color=color, centered=centered)
            bar.grid(row=row, column=1, pady=2)
            self.bars[key] = bar
        self.counters = tk.Label(live, text="", anchor="w", font=("Menlo", 10))
        self.counters.grid(row=4, column=0, columnspan=2, sticky="we")
        tk.Button(live, text="Calibrate centre (hold neutral, then click)",
                  command=self.calibrate).grid(row=5, column=0, columnspan=2,
                                               sticky="we", pady=(4, 0))

        # --- tuning ---
        tuning = tk.LabelFrame(root, text="Steering (applies live)")
        tuning.pack(fill="x", **pad)
        app_common.labeled_scale(tuning, 0, "Range (deg)", self.range, 10, 90, 1)
        app_common.labeled_scale(tuning, 1, "Smoothing", self.lowpass, 0.02, 1.0, 0.01)
        tk.Checkbutton(tuning, text="Invert", variable=self.invert).grid(
            row=2, column=0, sticky="w")
        tk.Checkbutton(tuning, text="Accel-only, axes:", variable=self.accel_only).grid(
            row=3, column=0, sticky="w")
        axes = tk.Frame(tuning)
        axes.grid(row=3, column=1, sticky="w")
        tk.Label(axes, text="lateral").pack(side="left")
        tk.Spinbox(axes, from_=0, to=2, width=2, textvariable=self.lateral).pack(side="left")
        tk.Label(axes, text=" vertical").pack(side="left")
        tk.Spinbox(axes, from_=0, to=2, width=2, textvariable=self.vertical).pack(side="left")

        # --- pedals / keys ---
        pedals = tk.LabelFrame(root, text="Pedals and buttons (gears by default)")
        pedals.pack(fill="x", **pad)
        tk.Checkbutton(pedals, text="Use keys (this window must be in front)",
                       variable=self.use_keys).grid(row=0, column=0, columnspan=4, sticky="w")
        names = list(KEY_CHOICES)
        for i, (role, label) in enumerate([("throttle", "Throttle"), ("brake", "Brake"),
                                           ("gear_up", "Button 1"), ("gear_down", "Button 2")]):
            r, c = 1 + i // 2, (i % 2) * 2
            tk.Label(pedals, text=label).grid(row=r, column=c, sticky="w")
            tk.OptionMenu(pedals, self.key_vars[role], *names).grid(row=r, column=c + 1, sticky="w")
        app_common.labeled_scale(pedals, 3, "Fixed throttle\n(keys off)", self.throttle, 0, 1, 0.05)

        root.protocol("WM_DELETE_WINDOW", self.close)

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
        def num(var, fallback):
            try:
                return var.get()
            except tk.TclError:  # half-typed spinbox value
                return fallback
        return {"range": max(1.0, self.range.get()), "lowpass": self.lowpass.get(),
                "invert": self.invert.get(), "use_keys": self.use_keys.get(),
                "throttle": self.throttle.get(), "accel_only": self.accel_only.get(),
                "lateral": num(self.lateral, 0), "vertical": num(self.vertical, 2),
                "rate": 100.0}

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
        s = self.settings()
        if s["accel_only"] and s["lateral"] == s["vertical"]:
            messagebox.showerror("Tilt Wheel", "Lateral and vertical axes must differ.")
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

        for role, var in self.key_vars.items():
            self.keys.bindings[role] = KEY_CHOICES[var.get()]

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
                self.counters.config(text=(
                    f"roll={st['roll']:+6.1f}d  sent={st['sent']}  "
                    f"rejected={st['rejected']}  nodata={st['nodata']}"))
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
