# PyInstaller spec for POCOBoard.
#
# Builds a *folder* distribution (dist/POCOBoard/) containing POCOBoard.exe
# and all Qt runtime DLLs.  Drag the whole folder to any Windows 10/11 box
# and double-click the .exe — no Python installation required.
#
# Rebuild with:   .\build.bat    (or: pyinstaller pocoboard.spec)

import os
from PyInstaller.utils.hooks import collect_submodules

APP_NAME = "POCOBoard"

# Make sure the Qt multimedia backend + video codec plugins are included so
# video playback and the low-latency audio sink work on machines without
# Qt installed system-wide.
hiddenimports = (
    collect_submodules("PySide6.QtMultimedia")
    + collect_submodules("PySide6.QtMultimediaWidgets")
    + ["shiboken6"]
)

a = Analysis(
    ["pocoboard.py"],
    pathex=[os.path.abspath(".")],
    binaries=[],
    datas=[
        # Ship the sample config next to the exe so first-time users can
        # rename it to config.ini and edit without hunting around.
        ("config.example.ini", "."),
        # Ship the icon next to the exe so Qt can pick it up at runtime
        # (window decorations, taskbar fallback). The icon is ALSO embedded
        # into the exe header (see icon= below) for Explorer.
        ("icon.ico", "."),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Shrink the dist by dropping Qt modules we don't use.
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore",
        "PySide6.Qt3DRender", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors",
        "PySide6.QtSerialPort", "PySide6.QtWebSockets", "PySide6.QtSql",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSpatialAudio",
        "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtTest",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                   # upx compression corrupts some Qt DLLs
    console=False,               # windowed app — no stray console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="icon.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
