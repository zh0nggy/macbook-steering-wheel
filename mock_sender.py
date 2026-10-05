"""Fake steering source. Runs on ANY machine, needs no Mac and no IMU.

This exists so two of you can build and tune the Windows side while the third
is still fighting IOKit. Build this into the pipeline first and confirm the car
steers in-game from a sine wave before real sensor data is involved.

    python mock_sender.py --host 192.168.1.42          # sweep left/right
    python mock_sender.py --host 192.168.1.42 --mode step
    python mock_sender.py --host 192.168.1.42 --mode center --throttle 0.4
"""

import argparse
import math
import socket
import time

import protocol


def steering_for(mode, elapsed, period):
    phase = (elapsed % period) / period
    if mode == "sweep":
        # smooth full-lock-to-full-lock sine: good for checking range + smoothness
        return math.sin(2.0 * math.pi * phase)
    if mode == "step":
        # hard left / centre / hard right: good for measuring latency by eye
        return [-1.0, 0.0, 1.0, 0.0][int(phase * 4) % 4]
    if mode == "center":
        return 0.0
    raise ValueError(f"unknown mode: {mode}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True, help="IP of the Windows PC")
    parser.add_argument("--port", type=int, default=protocol.DEFAULT_PORT)
    parser.add_argument("--rate", type=float, default=100.0, help="packets/sec")
    parser.add_argument("--mode", default="sweep", choices=["sweep", "step", "center"])
    parser.add_argument("--period", type=float, default=4.0, help="seconds per cycle")
    parser.add_argument("--throttle", type=float, default=0.0)
    parser.add_argument("--brake", type=float, default=0.0)
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = (args.host, args.port)
    interval = 1.0 / args.rate
    start = time.monotonic()
    seq = 0

    print(f"sending {args.mode} to {args.host}:{args.port} at {args.rate:.0f} Hz")
    print("ctrl-c to stop")
    try:
        while True:
            elapsed = time.monotonic() - start
            steer = steering_for(args.mode, elapsed, args.period)
            sock.sendto(
                protocol.pack(steer, args.throttle, args.brake, seq=seq), target
            )
            seq += 1
            if seq % int(args.rate) == 0:
                print(f"  t={elapsed:6.1f}s  steer={steer:+.3f}  sent={seq}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
