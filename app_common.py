"""Shared pieces for the two GUI apps: LAN discovery and simple bar widgets.

Discovery replaces "run ipconfig and type the address": the receiver
broadcasts a small beacon once a second on BEACON_PORT, and the sender lists
every PC it hears. This is a separate port and message from protocol.py, so
the frozen wire format is untouched.
"""

import math
import sys
import socket
import struct
import threading
import time
import tkinter as tk

BEACON_PORT = 5006
BEACON_MAGIC = b"TILTWHEEL1"

# Latency probe: the receiver sends each frame's timestamp straight back, and
# the sender compares it with its own clock. Only the sender's clock is used,
# so the two machines' clocks never need to agree. Separate from protocol.py.
ECHO_MAGIC = b"TWECHO"
_ECHO = struct.Struct("!6sd")
ECHO_SIZE = _ECHO.size


def pack_echo(timestamp):
    return _ECHO.pack(ECHO_MAGIC, timestamp)


def unpack_echo(data):
    """The echoed timestamp, or None if this isn't an echo packet."""
    if len(data) != ECHO_SIZE:
        return None
    magic, timestamp = _ECHO.unpack(data)
    return timestamp if magic == ECHO_MAGIC else None


# Reverse probe, so the Windows side can show a ping too: the receiver sends a
# PING with its own clock, the sender bounces the same bytes back as a PONG.
PING_MAGIC = b"TWPING"
PONG_MAGIC = b"TWPONG"


def pack_ping(timestamp):
    return _ECHO.pack(PING_MAGIC, timestamp)


def ping_to_pong(data):
    """If `data` is a PING, the matching PONG bytes to send back; else None."""
    if len(data) == ECHO_SIZE and data[:6] == PING_MAGIC:
        return PONG_MAGIC + data[6:]
    return None


def unpack_pong(data):
    """The receiver's original timestamp from a PONG, or None."""
    if len(data) != ECHO_SIZE:
        return None
    magic, timestamp = _ECHO.unpack(data)
    return timestamp if magic == PONG_MAGIC else None


def ping_display(stats):
    """Text + colour for a ping readout from a RollingStats of milliseconds."""
    summary = stats.summary()
    if summary is None:
        return "Ping: -- ms", "#888"
    avg, worst = summary
    # Under ~10 ms is excellent; over ~30 ms steering starts to feel delayed.
    color = "#1d7a35" if avg < 10 else "#b06000" if avg < 30 else "#c03030"
    return f"Ping: {avg:.1f} ms  (max {worst:.1f})", color


def low_latency_socket():
    """UDP socket marked as real-time traffic (DSCP EF, the "voice" class).

    WiFi routers with WMM, which is nearly all of them, put these packets in
    the highest-priority queue, so they wait less behind downloads and video.
    It's a hint: macOS honours it, Windows may ignore it, and nothing breaks
    either way.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, 0xB8)
    except (OSError, AttributeError):
        pass
    return sock


class OneEuroFilter:
    """Adaptive low-pass filter (Casiez et al., "1 Euro Filter", CHI 2012).

    A fixed smoothing factor forces a trade: enough smoothing to hide jitter
    when you hold still also adds lag when you turn. This filter changes its
    cutoff with speed: heavy smoothing when still (min_cutoff), light when
    moving fast (cutoff rises by beta per degree/second).
    """

    def __init__(self, min_cutoff=1.0, beta=0.3, d_cutoff=1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.value = None
        self._speed = 0.0

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def reset(self, value=None):
        self.value = value
        self._speed = 0.0

    def update(self, x, dt):
        if self.value is None or dt <= 0.0:
            self.value = x
            return x
        speed = (x - self.value) / dt
        self._speed += (speed - self._speed) * self._alpha(self.d_cutoff, dt)
        cutoff = self.min_cutoff + self.beta * abs(self._speed)
        self.value += (x - self.value) * self._alpha(cutoff, dt)
        return self.value


class RollingStats:
    """Average and maximum of samples from the last `window` seconds."""

    def __init__(self, window=1.0):
        self.window = window
        self._samples = []

    def add(self, value, now=None):
        now = time.monotonic() if now is None else now
        self._samples.append((now, value))
        self._trim(now)

    def _trim(self, now):
        cutoff = now - self.window
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.pop(0)

    def count(self, now=None):
        """How many samples arrived within the window (a rate, for a 1 s window)."""
        self._trim(time.monotonic() if now is None else now)
        return len(self._samples)

    def summary(self, now=None):
        """(average, maximum), or None if nothing arrived within the window."""
        self._trim(time.monotonic() if now is None else now)
        if not self._samples:
            return None
        values = [v for _t, v in self._samples]
        return sum(values) / len(values), max(values)


def local_ip():
    """Best guess at this machine's LAN address.

    Connecting a UDP socket sends nothing; it only asks the OS which interface
    it would route through, which is the address the other machine needs.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class BeaconSender:
    """Receiver side: call tick() from the receive loop, it rate-limits itself."""

    def __init__(self, data_port, interval=1.0):
        self.interval = interval
        self.next_at = 0.0
        name = socket.gethostname()[:40]
        self.message = b" ".join([BEACON_MAGIC, str(data_port).encode(), name.encode()])
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    def tick(self):
        now = time.monotonic()
        if now < self.next_at:
            return
        self.next_at = now + self.interval
        try:
            self.sock.sendto(self.message, ("<broadcast>", BEACON_PORT))
        except OSError:
            pass  # no network right now; keep trying quietly

    def close(self):
        self.sock.close()


class BeaconListener:
    """Sender side: collects {ip: (port, hostname, last_seen)} in a thread."""

    def __init__(self):
        self.found = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._sock = None
        self.error = None

    def start(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", BEACON_PORT))
            sock.settimeout(0.5)
        except OSError as exc:
            self.error = str(exc)
            return
        self._sock = sock
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self._stop.is_set():
            try:
                data, (ip, _) = self._sock.recvfrom(256)
            except socket.timeout:
                continue
            except OSError:
                break
            parts = data.split(b" ", 2)
            if len(parts) < 2 or parts[0] != BEACON_MAGIC:
                continue
            try:
                port = int(parts[1])
            except ValueError:
                continue
            name = parts[2].decode(errors="replace") if len(parts) > 2 else ip
            with self._lock:
                self.found[ip] = (port, name, time.monotonic())

    def recent(self, max_age=4.0):
        """[(ip, port, name)] heard within max_age seconds."""
        now = time.monotonic()
        with self._lock:
            return sorted(
                (ip, port, name)
                for ip, (port, name, seen) in self.found.items()
                if now - seen <= max_age
            )

    def stop(self):
        self._stop.set()
        if self._sock is not None:
            self._sock.close()


class Bar(tk.Canvas):
    """Horizontal meter. centered=True draws -1..+1 from the middle (steering),
    otherwise 0..1 from the left (pedals)."""

    def __init__(self, parent, color="#2b7de9", centered=False, width=320, height=22):
        super().__init__(
            parent, width=width, height=height, bg="#e6e6e6",
            highlightthickness=1, highlightbackground="#b0b0b0",
        )
        self.w, self.h = width, height
        self.centered = centered
        self.fill = self.create_rectangle(0, 0, 0, height, fill=color, width=0)
        if centered:
            self.create_line(width / 2, 0, width / 2, height, fill="#555")

    def set(self, value):
        if self.centered:
            mid = self.w / 2
            x = mid + max(-1.0, min(1.0, value)) * mid
            self.coords(self.fill, min(mid, x), 0, max(mid, x), self.h)
        else:
            self.coords(self.fill, 0, 0, max(0.0, min(1.0, value)) * self.w, self.h)


class DebugWindow:
    """Small separate window with the raw counters, kept out of the main UI.

    `read()` returns [(name, value, meaning)] and is polled while the window
    is open. Opening it again just brings the existing one to the front.
    """

    def __init__(self, parent, title, read):
        self.parent = parent
        self.title = title
        self.read = read
        self.win = None
        self.values = {}

    def open(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.lift()
            return
        self.win = tk.Toplevel(self.parent)
        self.win.title(self.title)
        self.win.resizable(False, False)
        self.values = {}
        for row, (name, value, meaning) in enumerate(self.read()):
            tk.Label(self.win, text=name, anchor="w", font=("Helvetica", 10, "bold")).grid(
                row=row, column=0, sticky="w", padx=(10, 6), pady=2)
            label = tk.Label(self.win, text=value, anchor="e", width=10,
                             font=("Menlo", 10) if sys.platform == "darwin" else ("Consolas", 10))
            label.grid(row=row, column=1, sticky="e", padx=6)
            tk.Label(self.win, text=meaning, anchor="w", fg="#666").grid(
                row=row, column=2, sticky="w", padx=(6, 10))
            self.values[name] = label
        self._tick()

    def _tick(self):
        if self.win is None or not self.win.winfo_exists():
            return
        for name, value, _meaning in self.read():
            if name in self.values:
                self.values[name].config(text=value)
        self.win.after(250, self._tick)

    def close(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.destroy()
        self.win = None


def labeled_scale(parent, row, text, var, low, high, step):
    """Label + slider + live value readout, laid out on one grid row.

    The value goes in its own label to the right rather than Tk's built-in
    readout above the bar, so the bar sits vertically centred on the label
    text (including two-line labels).
    """
    tk.Label(parent, text=text, anchor="w", justify="left").grid(
        row=row, column=0, sticky="w", padx=(0, 8), pady=3)
    tk.Scale(
        parent, variable=var, from_=low, to=high, resolution=step,
        orient="horizontal", length=200, showvalue=False,
    ).grid(row=row, column=1, sticky="we")

    # Format to the slider's step, e.g. step 0.05 -> "0.30", step 1 -> "45".
    decimals = max(0, len(f"{step:g}".partition(".")[2]))
    value = tk.Label(parent, width=5, anchor="w")
    value.grid(row=row, column=2, sticky="w", padx=(6, 0))

    def show(*_):
        try:
            value.config(text=f"{var.get():.{decimals}f}")
        except tk.TclError:
            pass

    var.trace_add("write", show)
    show()
