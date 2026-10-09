# MacBook Steering Wheel

Tilt your MacBook to steer in PC racing games. The Mac reads its built-in motion sensor and sends steering, throttle, brake and gear presses over WiFi to a Windows PC. The PC turns them into a virtual Xbox 360 controller, so the game sees an ordinary gamepad.

```
MacBook (sender_app.py)  --WiFi-->  Windows PC (receiver_app.pyw)  -->  virtual Xbox pad  -->  game
```

Works with any game that supports an Xbox controller.

## What you need

- An Apple Silicon MacBook with a motion sensor (support depends on the model).
- A Windows 10/11 PC that runs the game.
- Both machines on the same WiFi network.

## Windows setup

1. Install **Python 3** from [python.org](https://www.python.org/downloads/). During install, tick **"Add Python to PATH"**.
2. Install **ViGEmBus** (the virtual controller driver) from the [official releases page](https://github.com/nefarius/ViGEmBus/releases). Download `ViGEmBusSetup_x64.msi`, run it, and reboot if asked.
3. Install the Python package:
   ```bash
   python -m pip install vgamepad
   ```
4. Download this repo and double-click **`Start Receiver.bat`**.
5. Press **Start**. If Windows Firewall asks, click **Allow** (tick Private networks).

To check the virtual controller works, press **Test: fake sweep**, then open Win+R → `joy.cpl`. An "Xbox 360 Controller" should appear, and its stick moves left and right.

## Mac setup

1. Install **Python 3** from [python.org](https://www.python.org/downloads/macos/). It includes Tkinter, which the app needs. If you use Homebrew instead: `brew install python python-tk`.
2. Install the sensor library:
   ```bash
   python3 -m pip install macimu
   ```
3. Get the code. On the GitHub page click **Code → Download ZIP**, then open the ZIP in your Downloads folder to unzip it. This creates a folder called `macbook-steering-wheel-main`.
4. Open Terminal (Cmd+Space, type "Terminal") and run these three commands:
   ```bash
   cd ~/Downloads/macbook-steering-wheel-main
   chmod +x "Start Sender.command"
   xattr -dr com.apple.quarantine .
   ```
   The first goes into the project folder. The second makes the launcher runnable. The third stops macOS from blocking it with "Apple could not verify..." (this happens with downloaded files).

   If you unzipped it somewhere else, or used `git clone`, change the `cd` line to match. You can also type `cd `, drag the folder into Terminal, and press Enter.
5. Double-click **`Start Sender.command`** and enter your Mac password. Reading the motion sensor needs admin rights.

If you'd rather skip the launcher, run this from the project folder (after the `cd` above) instead:

```bash
sudo python3 sender_app.py
```

## Trying it without a MacBook

You can run the Mac app on Windows, with a slider standing in for the motion sensor:

```bash
python sender_app.py --demo
```

Drag **Fake tilt** to steer. Everything else (filtering, keys, network, ping) is the real code, so you can test the whole setup on one PC: open the receiver, press Start, then pick the PC in the demo window (or type `127.0.0.1`) and press **Start sending**.

## Playing

1. On Windows, open the receiver and press **Start**, **before** launching the game. Most games only look for controllers at startup.
2. On the Mac, your PC should appear in the **Windows PC** list. Click it. If the list stays empty, type the IP shown at the top of the receiver window ("This PC: ...").
3. Hold the MacBook by its base in your normal driving position, then click **Calibrate centre**.
4. Click **Start sending**. The receiver's status turns green.
5. In the receiver's **Game mapping** section, pick your game's preset (or set it up by hand), then launch the game.

**How to steer:** roll the laptop left and right, like tilting a tray. Spinning it flat like a wheel on a table won't register.

**Default keys on the Mac:**

| Key | Action |
|---|---|
| Left Shift | Throttle |
| Return | Brake |
| Tab | Button 1 (gear up) |
| Right Shift | Button 2 (gear down) |

Keys only work while the sender window is in front. You can change them in the sender app, or untick "Use keys" and set a fixed throttle.

If the Mac app closes or loses connection, the receiver centres the steering and releases the pedals within a quarter of a second.

## Game mapping

The receiver decides which part of the Xbox controller each input drives:

- **Preset:** ready-made layouts for Assetto Corsa, Forza, and two generic layouts. Changing any row switches it to Custom.
- **Steering / Throttle / Brake:** which stick or trigger each one uses.
- **Button 1 / Button 2:** which pad buttons the Mac's gear keys press.
- **Test:** presses that button once. Use it when a game's control settings wait for you to press a button to bind.

Settings are saved to `receiver_settings.json` and reload on the next start.

## Tuning

| Setting | Where | What it does |
|---|---|---|
| Range | Mac | Degrees of tilt for full lock. Lower means less movement needed. Adjust this first. |
| Steadiness | Mac | How much jitter is smoothed out while you hold still. Lower is steadier. |
| Turn response | Mac | How quickly smoothing backs off when you turn. Higher means less lag but more wobble. |
| Deadzone | PC | Ignores small wobbles around centre. |
| Gamma | PC | Above 1 gives finer control near centre. |
| Smoothing | PC | Extra smoothing. Leave at 0 unless steering is jittery. |
| Invert | Either | Flips steering direction. |

### Latency

Both windows show a **Ping** readout under the stats line: the round-trip time between the two machines, averaged over the last second, with the worst value in brackets. Each side measures it on its own, so the two numbers can differ slightly. The Mac also shows how many packets per second it's sending. Green (under 10 ms) is good. Orange or red means WiFi is the bottleneck. Try a less busy network, or turn on the PC's Mobile Hotspot and connect the Mac to it.

The rate is higher while you're turning (up to 250 per second) and drops to about 100 per second when you hold still.

Racing games often add their own controller smoothing or "steering assist". Turn those down in the game's settings, or correct steering can feel delayed.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Apple could not verify..." on the Mac | Run `xattr -dr com.apple.quarantine .` in the project folder, or allow it in System Settings → Privacy & Security → Open Anyway. |
| Mac app says it can't load macimu | Run `sudo python3 -m pip install macimu`. |
| Permission / root error | Open the app with `Start Sender.command` or `sudo python3 sender_app.py`. |
| PC doesn't appear in the Mac's list | Type the IP from the receiver window instead. |
| Receiver stays on "Waiting for the Mac..." | Check that both machines are on the same WiFi (not a guest network), and that Python is allowed through Windows Firewall. School and office WiFi often blocks devices from talking to each other; try a phone hotspot. |
| No controller in `joy.cpl` | ViGEmBus isn't installed, or needs a reboot. |
| Game doesn't react | Start the receiver before the game, then restart the game. Check the game's controller bindings match the mapping. |
| Steering goes the wrong way | Tick **Invert**. |
| Steering drifts off centre | Click **Calibrate centre** again. |
| `rejected` count climbs fast | You're sliding the laptop instead of tilting it in place. |
| Worked yesterday, not today | The PC's IP probably changed. Check the receiver window. |

## Files

| File | Runs on | Purpose |
|---|---|---|
| `receiver_app.pyw`, `Start Receiver.bat` | Windows | Receiver app |
| `sender_app.py`, `Start Sender.command` | Mac | Sender app |
| `pad_mapping.py` | Windows | Controller layouts and presets |
| `app_common.py` | Both | Network discovery and shared UI pieces |
| `protocol.py` | Both | Packet format. Keep the same copy on both machines. |
| `imu_reader.py` | Mac | Reads the motion sensor |
| `demo_imu.py` | Any | Fake sensor for `sender_app.py --demo` |
| `imu_probe.py` | Mac | Diagnostic: `sudo python3 imu_probe.py` checks the sensor, gyro and axes |
| `mac_sender.py`, `pad_receiver.py`, `mock_sender.py`, `key_input.py` | | Terminal versions of the apps. The apps reuse their code. |
