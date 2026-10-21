# PyInstaller spec for the Windows receiver: one TiltWheel-Receiver.exe, no
# console window. Build from the repo root:
#
#   python -m PyInstaller packaging/receiver.spec --noconfirm
#
# The exe still needs the ViGEmBus driver installed (a system driver, it can't
# be bundled). Settings are saved next to the exe (see app_common.app_dir).

from PyInstaller.utils.hooks import collect_all

ROOT = SPECPATH + "/.."

# vgamepad loads ViGEmClient.dll from a path next to its own files, so the
# whole package (DLLs included) has to come along.
vg_datas, vg_binaries, vg_hidden = collect_all("vgamepad")

a = Analysis(
    [ROOT + "/receiver_app.pyw"],
    pathex=[ROOT],
    binaries=vg_binaries,
    datas=vg_datas,
    hiddenimports=vg_hidden,
    # Mac-only sensor code: never imported by the receiver, keep it out.
    excludes=["macimu", "imu_reader", "mac_sender", "sender_app"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TiltWheel-Receiver",
    console=False,   # same as running it with pythonw
    upx=False,       # UPX-packed exes trip antivirus more often
)
