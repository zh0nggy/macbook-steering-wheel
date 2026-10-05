#!/bin/bash
# Double-click on the Mac to open the Tilt Wheel sender.
# macimu reads the motion sensor as root, so this asks for your password once.
# First time only: chmod +x "Start Sender.command"
cd "$(dirname "$0")" || exit 1
echo "Tilt Wheel needs your Mac password to read the motion sensor."
sudo python3 sender_app.py
