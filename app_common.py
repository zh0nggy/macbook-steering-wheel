"""Shared pieces for the two GUI apps: LAN discovery and simple bar widgets.

Discovery replaces "run ipconfig and type the address": the receiver
broadcasts a small beacon once a second on BEACON_PORT, and the sender lists
every PC it hears. This is a separate port and message from protocol.py, so
the frozen wire format is untouched.
"""

import math
import re
import socket
import struct
import subprocess
import sys
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


def is_link_local(ip):
    """169.254.x.x: what a direct cable link gets when there's no router."""
    return ip.startswith("169.254.")


def link_kind(ip):
    """'USB-C cable' for a direct cable link, else 'WiFi / LAN'."""
    return "USB-C cable" if is_link_local(ip) else "WiFi / LAN"


def _parse_ipconfig(text):
    """Windows `ipconfig` -> [(adapter, ip, mask)] for connected IPv4 adapters."""
    results = []
    adapter = ip = None
    for line in text.splitlines():
        if line and not line.startswith(" ") and line.rstrip().endswith(":"):
            adapter, ip = line.rstrip(":").strip(), None
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if "IPv4 Address" in key or "Autoconfiguration IPv4" in key:
            ip = re.sub(r"\(.*\)", "", value).strip()   # drop "(Preferred)"
        elif "Subnet Mask" in key and ip and adapter:
            results.append((adapter, ip, value))
            ip = None
    return results


def _parse_ifconfig(text):
    """macOS `ifconfig` -> [(interface, ip, mask)] for IPv4 interfaces."""
    results = []
    iface = None
    for line in text.splitlines():
        if line and not line[0].isspace():
            iface = line.split(":", 1)[0]
            continue
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+) netmask (0x[0-9a-fA-F]+)", line)
        if match and iface:
            mask_int = int(match.group(2), 16)
            mask = ".".join(str((mask_int >> s) & 0xFF) for s in (24, 16, 8, 0))
            results.append((iface, match.group(1), mask))
    return results


def interfaces():
    """[(name, ip, mask)] for this machine's IPv4 networks, loopback excluded.

    Uses the OS's own `ipconfig` / `ifconfig` so no extra package is needed.
    On failure, falls back to the single default-route address.
    """
    try:
        if sys.platform == "win32":
            text = subprocess.run(["ipconfig"], capture_output=True, text=True, timeout=3,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                                  ).stdout
            found = _parse_ipconfig(text)
        else:
            text = subprocess.run(["ifconfig"], capture_output=True, text=True,
                                  timeout=3).stdout
            found = _parse_ifconfig(text)
    except (OSError, subprocess.SubprocessError):
        found = []
    found = [(n, ip, m) for n, ip, m in found if not ip.startswith("127.")]
    if not found:
        ip = local_ip()
        if not ip.startswith("127."):
            found = [("default", ip, "255.255.255.0")]
    return found


def broadcast_address(ip, mask):
    to_int = lambda dotted: int.from_bytes(socket.inet_aton(dotted), "big")
    return socket.inet_ntoa(((to_int(ip) | (~to_int(mask) & 0xFFFFFFFF))
                             .to_bytes(4, "big")))


class BeaconSender:
    """Receiver side: call tick() from the receive loop, it rate-limits itself.

    Broadcasts on EVERY network this PC is on, not just the default route, so
    the Mac finds it over a USB-C cable link as well as over WiFi. Each
    interface gets its own socket bound to its address, because Windows sends
    a plain "<broadcast>" out of one interface only.
    """

    def __init__(self, data_port, interval=1.0, rescan=5.0):
        self.interval = interval
        self.rescan = rescan
        self.next_at = 0.0
        self.next_scan = 0.0
        name = socket.gethostname()[:40]
        self.message = b" ".join([BEACON_MAGIC, str(data_port).encode(), name.encode()])
        self.socks = {}      # ip -> (socket, broadcast address)
        self.addresses = []  # [(name, ip)] last seen, for the GUI
        self._lock = threading.Lock()

    def _scan(self):
        """Pick up cables being plugged in or unplugged. Runs in a thread so a
        slow `ipconfig` never stalls the steering loop."""
        found = interfaces()
        with self._lock:
            current = {ip for _n, ip, _m in found}
            for ip in list(self.socks):
                if ip not in current:
                    self.socks.pop(ip)[0].close()
            for _name, ip, mask in found:
                if ip in self.socks:
                    continue
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                    sock.bind((ip, 0))
                    self.socks[ip] = (sock, broadcast_address(ip, mask))
                except OSError:
                    continue
            self.addresses = [(n, ip) for n, ip, _m in found]

    def tick(self):
        now = time.monotonic()
        if now >= self.next_scan:
            self.next_scan = now + self.rescan
            threading.Thread(target=self._scan, daemon=True).start()
        if now < self.next_at:
            return
        self.next_at = now + self.interval
        with self._lock:
            targets = list(self.socks.values())
        for sock, bcast in targets:
            for dest in (bcast, "255.255.255.255"):
                try:
                    sock.sendto(self.message, (dest, BEACON_PORT))
                except OSError:
                    pass  # interface went away; the next rescan drops it

    def close(self):
        with self._lock:
            for sock, _ in self.socks.values():
                sock.close()
            self.socks.clear()


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
        """[(ip, port, name)] heard within max_age seconds.

        Cable links (169.254.x.x) sort first: when the same PC is reachable
        both ways, the cable is the faster, steadier choice. Beacons arrive
        every second and a rescan finds a newly plugged cable within ~5 s,
        so max_age leaves headroom for a missed beacon or two.
        """
        now = time.monotonic()
        with self._lock:
            return sorted(
                ((ip, port, name)
                 for ip, (port, name, seen) in self.found.items()
                 if now - seen <= max_age),
                key=lambda item: (not is_link_local(item[0]), item[0]),
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
