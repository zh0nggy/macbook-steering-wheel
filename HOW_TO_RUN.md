# Tilt Wheel — full build guide

Steering only. No assistant, no telemetry, no gear shifting. Those come after.

**This code has never been executed.** It was written but not run — the sandbox
lost filesystem access partway through the session. The wire format and steering
maths are sound. `imu_probe.py`'s API discovery is openly guessing at an
undocumented library, so that's where breakage is most likely. Budget an hour
for first-run fixes and don't panic when something throws.

---

## Part 0 — How this actually works

Read this even if you skim the rest. Two misconceptions cost real hours.

**The Mac is not a controller.** A laptop is a USB *host*, not a USB *device*.
It can drive a mouse; it cannot pretend to be one. No cable or setting changes
that. So nothing you plug into your PC will make Windows see a gamepad.

What Windows sees is a **fake controller created in software** by a driver
called ViGEmBus, running on the PC itself. The game reads that fake controller
and never knows a Mac exists. The Mac's only job is to shout numbers across the
network.

```
  MAC                          NETWORK              WINDOWS PC
  ───                          ───────              ──────────
  read tilt sensor
  compute roll angle
  steer = -1.0 … +1.0
  send UDP packet    ──────100×/sec──────▶   pad_receiver.py
                                                    │
                                             ViGEmBus driver
                                                    │
                                             fake Xbox pad
                                                    │
                                             Assetto Corsa
```

**Two programs run at the same time, one per machine.** `mac_sender.py` on the
Mac and `pad_receiver.py` on Windows, both open, both left running the whole
time you play. Neither does anything alone. This is the part that feels strange
at first.

**How you hold it.** An accelerometer measures which way gravity points, so:

- **Rolling** it left/right, like tilting a tray — gravity moves across the
  sensor. Fully visible. **This is your steering.**
- **Spinning** it flat, like a wheel on a table — gravity keeps pointing
  straight down through the same axis. **Zero signal. Invisible.**

The intuitive "hold it like a steering wheel and turn" gesture is precisely the
one that cannot work without a gyro. Sit down, hold the base with both hands
(not the screen), and roll. ±45° is a small controlled motion — you are not
swinging the machine around.

---

## Part 1 — The files

| File | Machine | Run it? | Purpose |
|---|---|---|---|
| `protocol.py` | both | no | Shared message format. A library, not a program. |
| `mock_sender.py` | Windows | day 1 | Fakes the Mac. Sends a smooth left/right sweep. |
| `pad_receiver.py` | Windows | always | Receives numbers → moves the fake pad. |
| `imu_reader.py` | Mac | no | Wrapper over macimu's real API. A library. |
| `imu_probe.py` | Mac | once | Finds which axis is which, checks the gyro. |
| `mac_sender.py` | Mac | always | Reads tilt → sends steering. |
| `vscode-launch.json` | Windows | no | Rename to `.vscode/launch.json` for F5 support. |

`protocol.py` must be **identical on both machines**. It defines the byte
layout: version, timestamp, steer, throttle, brake, counter. If one side's copy
drifts from the other's, you get numbers that look plausible and are garbage —
the worst bug class in this project. If you edit it, edit both copies in the
same commit.

On the Mac, `imu_probe.py` and `mac_sender.py` both import `imu_reader.py`, so
all three live in the same folder.

**Both Mac scripts need `sudo`.** macimu raises
`PermissionError: macimu requires root` otherwise. This means VS Code's F5 is
useless for the Mac side — it can't prompt for a password. Use the integrated
terminal there. The launch configs are Windows-only.

---

## Part 2 — Setup

### Windows PC

1. **Python 3** from python.org. Tick **"Add Python to PATH"** during install —
   miss it and every `python` command fails with "not recognized".
2. **VS Code** plus the **Python extension** (`ms-python.python`).
3. **ViGEmBus** from
   [the official releases page](https://github.com/nefarius/ViGEmBus/releases)
   only. This is a kernel-mode driver; do not use third-party mirrors or
   repacked installers. Grab `ViGEmBusSetup_x64.msi`, run it, reboot if asked.
4. `pip install vgamepad`
5. **Content Manager** (acstuff.ru) — not strictly required, but AC's stock
   input config is painful and you'll want CM's for step 9.

Note we are deliberately **not** using vJoy. Its original branch trips Windows
11 driver-signature enforcement, and the workarounds mean either disabling
signature enforcement system-wide or trusting an unofficial kernel driver.
Neither is worth it.

### Mac

1. **Python 3** — `python3 --version`. If missing, `brew install python`.
2. **VS Code** plus the Python extension.
3. `pip3 install macimu`

### Both

Open the **folder** in VS Code (File → Open Folder), not individual files. If
you open loose files, `${workspaceFolder}` in the launch configs won't resolve
and every config fails with a confusing path error.

Get your Windows PC's IP: run `ipconfig` **on the Windows PC** and read the
**IPv4 Address** line. Both machines on the same WiFi.

> **It must be a private address** — starting `192.168.`, `10.`, or
> `172.16`–`172.31`. Do **not** use an address from a "what's my IP" website.
> That returns your building's public router address, shared by everyone in the
> dorm; packets sent there leave your network entirely and go to a stranger's
> server. `mac_sender.py` now refuses to start on a public address, but know why.

> Dorm WiFi reassigns addresses periodically. If it worked yesterday and not
> today, re-check the IP before debugging anything else.

---

## Part 3 — Day 1: steering from fake data

**None of this needs the Mac or the sensor.** Two of you can do this while the
third fights IOKit. Only step 9 needs the machine that owns Assetto Corsa.

### Step 1 — Prove the network path

Two terminals in VS Code (Ctrl+` then the split button, or Ctrl+Shift+5). Both
on the Windows PC:

```powershell
python pad_receiver.py --dry-run
```

```powershell
python mock_sender.py --host 127.0.0.1
```

`127.0.0.1` means "this same machine" — no real network yet, which is the point.
Isolate one variable at a time.

**Check:** the receiver prints a steering value sweeping smoothly between about
`-1.000` and `+1.000`, once a second, and `dropped=0`.

**If nothing arrives:** Windows Firewall, roughly nine times in ten. Allow
Python inbound when prompted; if you dismissed that dialog, find it under
Windows Defender Firewall → Allow an app.

*Cheap to change later: everything here.*

### Step 2 — Prove the virtual pad

Drop `--dry-run`:

```powershell
python pad_receiver.py
```

With the mock still running, open **Run** (Win+R) → `joy.cpl` → double-click
the controller.

**Check:** "Xbox 360 Controller for Windows" is listed, and its left stick
crosshair sweeps left/right on its own.

This verification is worth doing properly. It separates "my driver works" from
"the game's input config is wrong" — conflate those two and you'll lose an hour.

**If no controller appears:** ViGEmBus didn't install. Check Device Manager for
"Nefarius Virtual Gamepad Emulation Bus". Reboot if you skipped it.

### Step 3 — Into the game

Start `pad_receiver.py` **before** launching AC. The virtual pad only exists
while that script runs, and the game scans for controllers at startup.

In Content Manager → Settings → Assetto Corsa → Controls, pick the **Gamepad**
preset. It should detect the Xbox pad and map left-stick-X to steering.

Then **turn the gamepad filters down**: speed-sensitive steering, steering
filter, steering gamma. AC applies its own smoothing to gamepads, which will
fight your response curve and make correct code feel broken. This trips
everyone up.

**Check:** with the mock sweeping, the car's wheels turn left and right on their
own in-game.

**That is your deployable checkpoint.** A demo exists from here even if the Mac
half never works. Record a screen capture the moment it happens.

> If you restart `pad_receiver.py` mid-session the pad disappears and
> reappears, and AC may drop the binding. Restart the game if inputs go dead.

---

## Part 4 — Day 2: real sensor

### Step 4 — Probe the IMU

On the Mac. **`sudo` is mandatory** — macimu talks to the sensor as root:

```bash
pip3 install macimu
sudo python3 imu_probe.py
```

Hold the laptop in your steering position and roll slowly left and right for
ten seconds, then Ctrl-C.

**Three things to read in the summary:**

1. **`fused orientation available: True`** — if so, macimu's own Mahony filter
   is doing gyro+accel fusion for you and you need no axis flags at all. This is
   the good path.
2. **`GYRO: LIVE`** or `no signal` — settles whether the M4 Air populates the
   gyro, which was the open question for this whole project.
3. **The accel axis table** — only needed for fallback mode. The last line
   prints the exact `--accel-only --lateral N --vertical N` flags if you need
   them.

**If it fails without sudo** you'll see
`PermissionError: macimu requires root`. That's expected, not a bug. It also
means VS Code's F5 can't run the Mac scripts, since it can't prompt for a
password — use the terminal.

**If there's no gyro:** doesn't block anything. Gravity-vector roll needs no
integration and therefore never drifts. You lose crispness, not function.

### Step 5 — Real steering

If step 4 said fused orientation works, you need **no axis flags**:

```bash
sudo python3 mac_sender.py --host 192.168.1.42
```

If it didn't, use the exact flags step 4 printed for you:

```bash
sudo python3 mac_sender.py --host 192.168.1.42 --accel-only --lateral 0 --vertical 2
```

**Use your real IP**, from `ipconfig` on the Windows PC. The script refuses to
start on a public address — see the warning in Part 2.

It asks you to hold the laptop at neutral and press Enter. That position becomes
centre, so hold it the way you'll actually sit while playing.

**Check:** the ASCII bar tracks your roll and sits centred when you hold
neutral. Add `--invert` if the car steers the wrong way.

Two counters, and they mean different things. `nodata` just means the sensor had
nothing new buffered that instant — harmless, ignore it. `rejected` means the
sample was dominated by linear acceleration rather than gravity, so if that one
climbs steadily you're translating the laptop instead of rolling it in place.

### Step 6 — Add throttle so the car actually drives

`--throttle` is already wired into `mac_sender.py` — no code edit needed. Enable
**automatic gearshifting** in AC's assists, then:

```bash
sudo python3 mac_sender.py --host 192.168.1.42 --throttle 0.3
```

The car pulls away at a modest constant speed, shifts itself, and steering is
the only thing you control. That's a complete honest demo, and it's what keeps
two days at two days.

Start at `0.3` and go lower if it's too fast to control — a slow car that you
steer well demos far better than a fast one you spin.

**To stop:** Ctrl-C on the Mac. The receiver's failsafe notices packets stopped,
centres the steering and cuts throttle to zero within 250 ms. That is your
brake for now, and it's also what saves you if the Mac crashes mid-corner —
without it the car would hold full lock into a wall.

---

## Part 5 — Tuning

In this order. Changing several at once means you can't tell what helped.

| Flag | Where | Start | Does what |
|---|---|---|---|
| `--range` | mac_sender | 45 | Degrees of roll for full lock. **Tune first.** |
| `--gamma` | pad_receiver | 1.5 | >1 gives finer control near centre. |
| `--deadzone` | pad_receiver | 0.05 | Kills twitch when you hold neutral. |
| `--lowpass` | mac_sender | 0.15 | Higher = smoother, laggier. |
| `--smooth` | pad_receiver | 0.0 | Second smoothing stage. Leave at 0 unless desperate. |

Lower `--range` usually feels better than higher — a wheel needing less body
movement beats one needing more.

You have roughly **20 ms** of end-to-end latency before steering feels
disconnected from your hands. Both smoothing knobs spend that budget. Spend
reluctantly.

Borrow a real gamepad and compare side by side if any of you has one. "Does
this feel right" is not answerable from inside your own filter, and none of you
sim-races, so you have no baseline intuition to fall back on.

---

## Part 6 — Splitting the work

| Person | Owns | Can start immediately? |
|---|---|---|
| A | Windows: driver, receiver, `joy.cpl`, tuning, AC input config | Yes |
| B | Mac: `imu_probe`, axis discovery, `mac_sender`, calibration | Yes |
| C | Latency measurement, README, demo recording, git hygiene | Yes |

Everyone reviews everyone's PRs. With a clean three-way split each of you can
otherwise only defend a third of the project in an interview, and "I did the
networking" is a much weaker line than the project deserves. Make sure all
three of you can explain why gyro integration drifts and what the accelerometer
fixes — that's the question you'll actually get asked.

---

## Part 7 — Troubleshooting

| Symptom | Cause |
|---|---|
| `python: command not found` | PATH not set at install. Reinstall, tick the box. |
| Receiver prints nothing | Windows Firewall. Or wrong IP. Or wrong subnet. |
| No controller in `joy.cpl` | ViGEmBus not installed / needs reboot. |
| Car steers but feels laggy | Lower `--lowpass` and `--smooth`; check `dropped`. |
| Car twitches at neutral | Raise `--deadzone`. |
| Steering backwards | `--invert` on `mac_sender`. |
| Steering feels muted or delayed in-game only | AC's gamepad filters. Part 3, step 3. |
| Wheel drifts off-centre over time | You changed how you're holding it. Restart to recalibrate. |
| `rejected` climbing fast | You're translating the laptop, not rolling it. |
| `nodata` climbing | Harmless — sensor buffer was empty that instant. |
| `AttributeError: 'list' object has no attribute 'x'` | Old `imu_reader.py`. The read methods return a *list* of Samples. |
| Worked yesterday, dead today | WiFi handed out a new IP. Re-run `ipconfig`. |
| `--host` required error | You pressed ▶ instead of F5, or used the wrong launch config. |
| `PermissionError: macimu requires root` | Use `sudo python3 ...`. Expected, not a bug. |
| "NOT a local network address" | You used a public IP. Run `ipconfig` on the PC. |
| Mac sends fine, PC receives nothing | Wrong IP, or the two machines are on different WiFi networks (e.g. one on guest). |

---

## Part 8 — What's permanent, what isn't

**Cheap to change:** every tuning constant, the response curve, axis choice,
packet rate, keybindings. Flags or one-line edits.

**Expensive to change:** the wire format in `protocol.py` once both sides depend
on it, and the decision to run the game on Windows rather than under CrossOver
on the Mac. Both are load-bearing — changing either means touching everything.

---

## Part 9 — After the MVP

**Gears and brakes on the Mac keyboard.** Your hands are already there. Capture
keys with `pynput`, put their state in the packet you're already sending, map
them to pad buttons in the receiver. Needs macOS Accessibility permission.
Test which keys you can physically reach while holding your steering grip
*before* picking bindings.

One trap. Steering is a **state** — sending `0.42` a hundred times a second
just means the wheel is still at 0.42. A gear shift is an **event**. Send
`gear_up=true` at 100 Hz while holding the key for 200 ms and the game sees
twenty upshifts. Fix: send a shift **counter** that only increases, and have
the receiver pulse the button once when the number changes. Throttle and brake
are states like steering, so they're straightforward. Only gears bite.

**Sensor fusion — already done for you.** macimu ships a `MahonyAHRS` class and
exposes fused roll through `IMU.orientation`, which is what `mac_sender.py` uses
by default. You get gyro responsiveness plus accelerometer drift correction
without writing a filter.

Worth understanding rather than just using, because it's the most likely
interview question here: the gyro measures rotation *rate*, so recovering angle
means integrating, and tiny errors accumulate until the reading is useless
within seconds. The accelerometer gives an absolute reference from gravity but
is noisy and gets corrupted by any linear movement. Fusion trusts the gyro
short-term and lets the accelerometer pull it back long-term. Neither sensor
works alone; that's the whole point.

If you want the hands-on version, write a complementary filter over
`read_gyro()` and `read_accel()` and compare it against `orientation` —
`angle = a*(angle + rate*dt) + (1-a)*accel_angle`, `a ≈ 0.98`. Good learning,
not required.

**The assistant.** Read AC's shared memory (`acpmf_physics`, `acpmf_graphics`)
for speed, gear and track position. Record your own laps, bin by
`normalizedCarPosition`, regress position → speed and gear. Since none of you
sim-races, target **your own personal-best pace, not optimal pace** — honest,
defensible, and it improves as you do. Deliver it as **speech**, not an overlay;
you can't read text while steering. Query *ahead* of the car
(`position + speed × 1.5s`) or the advice arrives after the corner. Pre-render
the phrases to wav files — synthesis latency will wreck timing that playback
won't.

---

## Minimum path if you only get four hours

Steps 1, 2, 3 with the mock. That's a car steering itself in a real game from
your code, on video. Everything after is upside.

---

## Sources

- [nefarius/ViGEmBus](https://github.com/nefarius/ViGEmBus) — virtual pad driver ([install docs](https://docs.nefarius.at/projects/ViGEm/How-to-Install/))
- [vgamepad](https://github.com/yannbouteiller/vgamepad) — Python binding
- [macimu](https://pypi.org/project/macimu/) — IMU access; usage 3 = accel, usage 9 = gyro, via `AppleSPUHIDDriver`
- [olvvier/apple-silicon-accelerometer](https://github.com/olvvier/apple-silicon-accelerometer) — original reverse-engineering, ~800 Hz over IOKit HID
