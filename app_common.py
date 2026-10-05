"""Shared pieces for the two GUI apps: LAN discovery and simple bar widgets.

Discovery replaces "run ipconfig and type the address": the receiver
broadcasts a small beacon once a second on BEACON_PORT, and the sender lists
every PC it hears. This is a separate port and message from protocol.py, so
the frozen wire format is untouched.
"""

import socket
import threading
import time
import tkinter as tk

BEACON_PORT = 5006
BEACON_MAGIC = b"TILTWHEEL1"


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


def labeled_scale(parent, row, text, var, low, high, step):
    """Label + slider + live value readout, laid out on one grid row."""
    tk.Label(parent, text=text, anchor="w").grid(row=row, column=0, sticky="w", padx=(0, 8))
    tk.Scale(
        parent, variable=var, from_=low, to=high, resolution=step,
        orient="horizontal", length=200, showvalue=True,
    ).grid(row=row, column=1, sticky="we")
