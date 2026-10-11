# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller configuration for the PySide6 + React desktop application."""

from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_dynamic_libs


ROOT = Path(SPECPATH)
ONEDIR = "--onedir" in sys.argv
FRONTEND_DIST = ROOT / "prototype" / "dist" / "client"
if not (FRONTEND_DIST / "index.html").is_file():
    raise SystemExit(
        "Missing prototype/dist/client/index.html; run the frontend production build first."
    )


a = Analysis(
    [str(ROOT / "novelreader" / "main.py")],
    pathex=[str(ROOT)],
    binaries=collect_dynamic_libs("sherpa_onnx"),
    datas=[
        (str(ROOT / "assets" / "app.ico"), "assets"),
        (str(FRONTEND_DIST), "prototype/dist/client"),
    ],
    hiddenimports=[
        "pyttsx3.drivers",
        "pyttsx3.drivers.sapi5",
        "edge_tts",
        "aiohttp",
        "pycaw",
        "pycaw.pycaw",
        "pycaw.api",
        "comtypes",
        "psutil",
        "sherpa_onnx",
        "sherpa_onnx.lib._sherpa_onnx",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "idlelib",
        "test",
        "tkinter",
        "tkinterdnd2",
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DRender",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtGraphs",
        "PySide6.QtGraphsWidgets",
        "PySide6.QtLocation",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtQuick3D",
        "PySide6.QtRemoteObjects",
        "PySide6.QtScxml",
        "PySide6.QtSensors",
        "PySide6.QtSerialBus",
        "PySide6.QtSerialPort",
        "PySide6.QtSpatialAudio",
        "PySide6.QtStateMachine",
        "PySide6.QtTest",
        "PySide6.QtTextToSpeech",
        "PySide6.QtWebView",
    ],
    noarchive=False,
    optimize=0,
)

# This application renders React in QWebEngineWidgets and never loads QML.
# PyInstaller follows QtWebEngine's optional QtQuick dependency and otherwise
# adds the whole PySide6/qml tree (including 3D and virtual-keyboard plugins).
# The native QtQml/QtQuick libraries required by WebEngine remain untouched.
def _without_qml_tree(entry):
    target = entry[0].replace("\\", "/").lower()
    return not target.startswith("pyside6/qml/")


a.binaries = [entry for entry in a.binaries if _without_qml_tree(entry)]
a.datas = [entry for entry in a.datas if _without_qml_tree(entry)]
pyz = PYZ(a.pure)

if ONEDIR:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="QYReader",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=[str(ROOT / "assets" / "app.ico")],
    )
    app = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="QYReader",
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="QYReader",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=[str(ROOT / "assets" / "app.ico")],
    )
