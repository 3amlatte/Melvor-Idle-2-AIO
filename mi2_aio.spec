# PyInstaller spec for the MI2 AIO desktop app.
# Build with: .\scripts\build_app.ps1
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve()

a = Analysis(
    ["run_app.py"],
    pathex=[str(ROOT / "src")],
    binaries=[(str(ROOT / "tools" / "bin" / "SaveTool.exe"), "tools/bin")],
    datas=[
        (str(ROOT / "config"), "config"),
        (str(ROOT / "data"), "data"),
        (str(ROOT / "assets"), "assets"),
    ],
    hiddenimports=collect_submodules("mi2_aio"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MI2 AIO",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / "assets" / "icon.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="MI2 AIO",
)
