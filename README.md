# MacBook Steering Wheel

Tilt your MacBook to steer in PC racing games. The Mac reads its built-in motion sensor and sends steering, pedals and any controller button you bind to a key over WiFi to a Windows PC. The PC turns them into a virtual Xbox 360 controller, so the game sees an ordinary gamepad.

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

## Android phone instead of a Mac

The `android/` folder has a phone app that talks to the same receiver. Hold the phone in landscape and turn it like a steering wheel. The app opens on a page to pick your Windows PC, then switches to the steering page: tilt to steer, plus any touch buttons you laid out on the PC. How far you turn for full lock is the **Range** slider in the receiver's Android tuning (45° by default); Deadzone, Gamma, Smoothing and Invert apply as usual (see [Tuning](#tuning)).

**Phone buttons:** clicking **Android** in the receiver opens a Phone layout window. Click a button on the controller picture to add a box for it to the phone drawing, drag boxes to move them, drag a box's corner to resize it, and right-click to remove it. Each button can be added once; its zone on the controller fills in while it's on the phone. While the phone is sending, the layout appears on its steering page within a second, and holding a box presses that pad button (LT/RT boxes are full brake / throttle).

1. Install [Android Studio](https://developer.android.com/studio) and let its setup wizard download the SDK.
2. On the phone: **Settings → About phone**, tap **Build number** 7 times, then turn on **Developer options → USB debugging**. Plug it in and allow the PC.
3. In Android Studio, choose **Open** and pick the `android` folder. Wait for Gradle sync, then press **Run** (green triangle) with your phone selected.
4. Start the receiver on the PC, click **Android** next to "This PC", and press **Start**. Then open the app, tap your PC in the list (or type the IP shown in the receiver window) and tap **Start sending**. The app moves to the steering page and the receiver's status turns green. Hold the phone straight and tap **Calibrate centre**. **Stop** (or the back button) returns to the PC page.

Use either the phone or the Mac, not both at once. The receiver follows whichever sent last.

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
5. Set your keys on the controller picture in the Mac app (see [Setting your keys](#setting-your-keys)), then launch the game.

**How to steer:** roll the laptop left and right, like tilting a tray. Spinning it flat like a wheel on a table won't register.

If the Mac app closes or loses connection, the receiver centres the steering and releases the pedals and every button within a quarter of a second.

## Setting your keys

The Mac app shows an Xbox controller. To choose a key for any button:

1. Click the button on the controller picture. It turns yellow and shows `?`.
2. Press the Mac key you want. The key's name appears on the button.

Press **Esc** to cancel, or **Backspace** to clear a button. Giving a key to a second button moves it off the first. **Reset to defaults** restores the starting keys.

Every button can be bound: A/B/X/Y, both bumpers, both triggers, View, Menu, the Xbox button, the four D-pad directions and both stick clicks. Tilt always drives the left stick. A key on a trigger ramps it up smoothly while held, like a pedal.

**Defaults:**

| Key | Controller | Typical use |
|---|---|---|
| Right Shift | Left trigger | Brake |
| Left Shift | Right trigger | Throttle |
| Tab | A | Gear up (Assetto Corsa) |
| Return | X | Gear down (Assetto Corsa) |

**Invert** steering is on by default. Untick it if the car turns the wrong way. If you set keys before, press **Reset to defaults** to switch to these, since saved keys take priority.

While a key is held, its button lights up blue, so you can see exactly what's being sent. Keys only work while the sender window is in front. **Fixed throttle** holds the right trigger at a set level (cruise control); 0 turns it off.

Bindings are saved to `sender_settings.json` on the Mac and reload on the next start. Then bind the same buttons in the game's own controller settings.

## Tuning

The receiver keeps a separate set of PC settings for each device. Click **Mac** or **Android** next to "This PC" in the receiver window; the sliders switch to that device's values, and each set is saved on its own.

| Setting | Where | What it does |
|---|---|---|
| Range | Mac / PC (Android) | Degrees of tilt for full lock. Lower means less movement needed. Adjust this first. The Mac sets it in the sender app; for the phone it's in the receiver, shown only when Android is selected. |
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
| `rejected` climbs fast (Mac **Debug** window) | You're sliding the laptop instead of tilting it in place. |
| `loss` over ~10% (PC **Debug** window) | WiFi is losing packets. Try a less busy network or a phone hotspot. |
| Worked yesterday, not today | The PC's IP probably changed. Check the receiver window. |

## Making a release

Pushing a version tag builds everything on GitHub and publishes a release with three downloads: the Android app (`.apk`), the Windows receiver as a single `.exe` (no Python needed, ViGEmBus still is), and a zip of the Mac sender.

```bash
git tag v1.0.0
```

```bash
git push origin v1.0.0
```

The version in the tag becomes the app's version, so there's nothing to edit by hand. The workflow is `.github/workflows/release.yml`; **Actions → Release → Run workflow** builds the files without publishing, to test.

**One-time: Android signing key.** Phones only install signed apps, and updates must be signed with the same key, so make one and keep it safe (back it up; a lost key means users have to uninstall to update). With Android Studio's Java:

```bash
keytool -genkeypair -v -keystore tiltwheel-release.jks -alias tiltwheel -keyalg RSA -keysize 2048 -validity 10000
```

Keep the `.jks` outside the repo, then add four secrets under the repo's **Settings → Secrets and variables → Actions**: `ANDROID_KEYSTORE_BASE64` (the file base64-encoded, e.g. `base64 -w0 tiltwheel-release.jks`), `ANDROID_STORE_PASSWORD`, `ANDROID_KEY_ALIAS` (`tiltwheel`) and `ANDROID_KEY_PASSWORD`. Without them the release still builds, but the APK is unsigned.

**Building locally:** for a signed APK, create `android/keystore.properties` (gitignored) with `storeFile`, `storePassword`, `keyAlias` and `keyPassword`, then run `gradlew assembleRelease` in `android/`. For the receiver exe:

```bash
python -m pip install -r packaging/requirements-build.txt
```

```bash
python -m PyInstaller packaging/receiver.spec --noconfirm
```

The exe lands in `dist/` and saves its settings next to itself.

On a build machine without ViGEmBus, set `VGAMEPAD_SKIP_VIGEMBUS_INSTALL=true`
before installing the build requirements (`$env:VGAMEPAD_SKIP_VIGEMBUS_INSTALL = "true"`
in PowerShell). This skips the interactive driver installer; the release workflow
sets it automatically. Players still need to install ViGEmBus on their gaming PC.

## Files

| File | Runs on | Purpose |
|---|---|---|
| `receiver_app.pyw`, `Start Receiver.bat` | Windows | Receiver app |
| `sender_app.py`, `Start Sender.command` | Mac | Sender app |
| `controller_view.py` | Mac | Clickable controller picture for key bindings |
| `phone_layout.py` | Windows | Phone layout window: where the phone's touch buttons go |
| `android/` | Android | Phone app (open this folder in Android Studio) |
| `packaging/`, `.github/workflows/release.yml` | | Release builds: receiver exe spec and the GitHub release workflow |
| `pad_mapping.py` | Windows | Turns received buttons into virtual pad presses |
| `app_common.py` | Both | Network discovery and shared UI pieces |
| `protocol.py` | Both | Packet format. Keep the same copy on both machines. |
| `imu_reader.py` | Mac | Reads the motion sensor |
| `demo_imu.py` | Any | Fake sensor for `sender_app.py --demo` |
| `imu_probe.py` | Mac | Diagnostic: `sudo python3 imu_probe.py` checks the sensor, gyro and axes |
| `mac_sender.py`, `pad_receiver.py`, `mock_sender.py`, `key_input.py` | | Terminal versions of the apps. The apps reuse their code. |

Written by Dimitar Martin Iliev
