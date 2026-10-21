# Steering Wheel Emulator

Use an Android phone or a supported Apple Silicon MacBook to steer in Windows racing games over WiFi. TiltWheel sends steering, pedals, and buttons to a Windows receiver, which presents them to the game as a virtual Xbox 360 controller.

```text
Android phone or MacBook  --WiFi-->  Windows receiver  -->  virtual Xbox controller  -->  game
```

For PC games that support Xbox controllers.

## Download

**[Download the latest release](https://github.com/zh0nggy/steering-wheel-emulator/releases/latest)** and expand **Assets** if the downloads are hidden.

Download the **Windows receiver** and **one sender** for your phone or Mac:

| Device | Release file | What you need |
|---|---|---|
| Windows gaming PC | `TiltWheel-Receiver-<version>.exe` | Windows 10/11, 64-bit, and the ViGEmBus driver. Python is bundled. |
| Android phone | `TiltWheel-<version>.apk` | Android 8.0 or newer with an accelerometer. Install the APK directly; Android Studio is not required. |
| MacBook | `TiltWheel-Mac-Sender-<version>.zip` | A supported Apple Silicon MacBook with a motion sensor, Python with Tkinter, and `macimu`. |

For example, the first release contains `TiltWheel-Receiver-0.1.0.exe`, `TiltWheel-0.1.0.apk`, and `TiltWheel-Mac-Sender-0.1.0.zip`.

Use packages from the same release on both devices. The automatic **Source code** archives are for development; the files above are the release downloads.

Both devices must be on the same local network. Use one sender at a time: the receiver follows whichever device sent last.

## 1. Set up the Windows receiver

1. Install **ViGEmBus**, the virtual controller driver, from its [official releases page](https://github.com/nefarius/ViGEmBus/releases). Run the x64 installer and reboot if requested.
2. Download `TiltWheel-Receiver-<version>.exe` from the TiltWheel release.
3. Put the EXE in a folder you can write to, such as `Documents\TiltWheel`. The receiver saves its settings and phone layout beside the EXE.
4. Double-click the EXE and choose **Android** or **Mac** next to **This PC**.
5. Press **Start**. If Windows Firewall asks, allow the receiver on **Private networks**.
6. Start the receiver before launching your game.

The Windows release does not require Python, Java, or a separate `vgamepad` installation.

To check the virtual controller, press **Test: fake sweep**, then press Win+R and enter `joy.cpl`. An Xbox 360 controller should appear and its stick should move left and right. Press **Stop fake sweep** before connecting your sender. Leave **Dry run (no virtual pad)** unchecked when playing.

## 2. Set up your sender

Choose Android or Mac.

### Android phone

1. On your phone, open the [latest release](https://github.com/zh0nggy/steering-wheel-emulator/releases/latest) and download `TiltWheel-<version>.apk`.
2. Open the APK. If Android asks, allow your browser or file manager to **install unknown apps**, then complete the installation.
3. Connect the phone to the same WiFi network as your PC and open **Tilt Wheel**.
4. With the Windows receiver started and **Android** selected, tap your PC in the phone's list. If it does not appear, enter the IP address shown beside **This PC** in the receiver.
5. Tap **Start sending**. Hold the phone in landscape in your neutral driving position and tap **Calibrate centre**.
6. Turn the phone like a steering wheel. The receiver's status should turn green and its steering meter should move.

Tap **Stop**, or use the back button, to return to the PC selection page.

**Add touch buttons:** selecting **Android** in the receiver opens the Phone layout window. Click a button on the controller picture to add it to the phone drawing. Drag a box to move it, drag its corner to resize it, and right-click to remove it. Each button can be added once.

While connected, layout edits appear on the phone within about a second. Hold a box to press that controller button. **LT** and **RT** boxes apply full brake and throttle.

### MacBook

The Mac release is a ZIP of the sender scripts and launcher. It still needs Python and the sensor library; it is not a standalone macOS app.

1. Install **Python 3** from [python.org](https://www.python.org/downloads/macos/), which includes Tkinter.
2. Open Terminal and install the sensor library:

   ```bash
   python3 -m pip install macimu
   ```

3. Download `TiltWheel-Mac-Sender-<version>.zip` from the release and unzip it.
4. In Terminal, type `cd ` (including the space), drag the extracted sender folder into the Terminal window, and press Enter. This selects the correct folder regardless of the release version or where you extracted it.
5. Make the launcher executable:

   ```bash
   chmod +x "Start Sender.command"
   ```

6. Double-click **Start Sender.command** in Finder and enter your Mac password when requested. Reading the motion sensor requires admin rights.

   You can also start it from Terminal in the sender folder:

   ```bash
   sudo python3 sender_app.py
   ```

7. With the Windows receiver started and **Mac** selected, choose your PC in the sender's **Windows PC** list. If it does not appear, enter the IP shown in the receiver.
8. Hold the MacBook by its base in your normal driving position and click **Calibrate centre**.
9. Click **Start sending**, configure your keys below, then launch the game on the PC.

To steer, roll the laptop left and right like tilting a tray. Spinning it flat on a table does not produce the same motion. Motion sensor support depends on the MacBook model.

If macOS blocks the launcher, allow it through **System Settings → Privacy & Security → Open Anyway**, where available. Alternatively, from inside the extracted sender folder, remove its download quarantine:

```bash
xattr -dr com.apple.quarantine .
```

## Controls

### Mac keyboard bindings

Click a button on the controller picture, then press the key you want to assign. Press **Esc** to cancel or **Backspace** to clear the binding. Assigning a key to another button moves it from the previous button.

| Default key | Controller input | Typical use |
|---|---|---|
| Right Shift | Left trigger | Brake |
| Left Shift | Right trigger | Throttle |
| Tab | A | Gear up |
| Return | X | Gear down |

Every controller button can be bound: A/B/X/Y, bumpers, triggers, View, Menu, Xbox, D-pad directions, and stick clicks. Tilt drives the left stick. Trigger keys ramp up smoothly while held.

Keep the sender window in front: it reads keys only while focused. Pressed buttons light up blue. **Fixed throttle** holds the right trigger at a chosen level; set it to 0 to turn it off.

**Invert** is enabled by default in the Mac sender. Change it if steering goes the wrong way. Saved bindings take priority over defaults; use **Reset to defaults** to restore the table above.

Bindings and sender settings are saved beside the Mac scripts in `sender_settings.json`. Configure the corresponding controls in your game's controller settings.

### Connection loss

If the sender stops or the connection is lost, the receiver centres steering and releases pedals and buttons after about a quarter of a second.

## Tuning

The receiver saves separate tuning profiles for Mac and Android. Choose the device beside **This PC** to adjust its profile.

| Setting | Where | What it does |
|---|---|---|
| Range | Mac sender / receiver for Android | Degrees of tilt for full lock; 45° by default. Lower values need less movement. Adjust this first. |
| Steadiness | Mac sender | Lower values smooth more jitter while holding still. |
| Turn response | Mac sender | Higher values respond faster during turns, with less smoothing. |
| Deadzone | Receiver | Ignores small movements around centre. |
| Gamma | Receiver | Values above 1 give finer control near centre. |
| Smoothing | Receiver | Adds smoothing. Leave at 0 unless steering is jittery. |
| Invert | Sender or receiver | Reverses steering direction. |

The **Ping** display shows average round-trip time, with the maximum in brackets. Under 10 ms is a good target. If latency or packet loss is high, try a less busy WiFi network or connect your sender to the PC's Mobile Hotspot.

Some games add controller smoothing or steering assist. Reducing those settings may improve steering response.

## Updating

1. Download the Windows receiver and your sender from the same new release.
2. Close the running apps.
3. Replace the Windows EXE in its existing folder to keep `receiver_settings.json` and `phone_layout.json`.
4. On Android, install the new APK over the existing app. Release updates must be signed with the same key. A previously installed Android Studio debug build may need to be uninstalled first.
5. On Mac, extract the new ZIP into a new folder. Copy `sender_settings.json` from your previous sender folder if you want to keep your settings, then launch the new sender.

## Troubleshooting

| Problem | What to check |
|---|---|
| No controller in `joy.cpl` | Install ViGEmBus and reboot if requested. Make sure **Dry run** is unchecked. |
| Receiver stays on “Waiting…” | Start sending on the phone or Mac. Check both devices are on the same network and the receiver is allowed through Windows Firewall. |
| PC does not appear in the sender list | Enter the receiver's **This PC** IP manually. Guest, school, and office networks may block communication between devices; try a hotspot. |
| APK will not install | Check the phone runs Android 8.0 or newer, permit installation from your browser/file manager, and use a signed release APK. If replacing a debug build, uninstall that build first. |
| Mac cannot load `macimu` | Install it for the Python used by the launcher. If it is missing when launched with `sudo`, use `sudo python3 -m pip install macimu`. |
| Mac reports a permission/root error | Launch with **Start Sender.command** or `sudo python3 sender_app.py`. |
| macOS blocks the launcher | Follow the Mac setup instructions above for **Open Anyway** or removing the extracted folder's quarantine. |
| Game does not react | Start the receiver before launching the game, turn off **Dry run**, and check the game's controller bindings. |
| Steering goes the wrong way | Toggle **Invert**. |
| Steering drifts off centre | Hold the sender neutral and use **Calibrate centre** again. |
| Settings are not retained on Windows | Keep the EXE in a writable folder and preserve the JSON files beside it. |
| Mac Debug shows many rejected sensor samples | Tilt the laptop in place instead of sliding it sideways. |
| High packet loss or ping | Try a less busy network or the PC's Mobile Hotspot. |
| Connection worked before but fails now | Check whether the PC's IP address changed. |

Written by Dimitar Martin Iliev
