# -*- mode: python ; coding: utf-8 -*-
# Spécification PyInstaller : python -m PyInstaller packaging/tcfmaster.spec --noconfirm
# Produit dist/WhiteTekTCF/WhiteTekTCF.exe (mode dossier, démarrage rapide).
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent
PKG = ROOT / "tcfmaster"

datas = [
    (str(PKG / "content" / "data"), "tcfmaster/content/data"),
    (str(PKG / "assets"), "tcfmaster/assets"),
    (str(PKG / "docs"), "tcfmaster/docs"),
]
for optional, dest in ((PKG / "content" / "audio", "tcfmaster/content/audio"),
                       (PKG / "models", "tcfmaster/models")):
    if optional.is_dir():
        datas.append((str(optional), dest))
datas += collect_data_files("vosk")
datas += collect_data_files("_sounddevice_data")
binaries = collect_dynamic_libs("vosk")

hiddenimports = [
    "pyttsx3.drivers", "pyttsx3.drivers.sapi5", "win32com.client", "pythoncom",
    "keyring.backends.Windows", "PySide6.QtCharts", "PySide6.QtMultimedia",
    "sqlalchemy.dialects.sqlite", "anthropic",
]

a = Analysis(
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="WhiteTekTCF",
    console=False,
    icon=str(PKG / "assets" / "app.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="WhiteTekTCF")
