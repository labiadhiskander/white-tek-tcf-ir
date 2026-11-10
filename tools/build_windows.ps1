# Construction locale de l'installateur Windows (équivalent du workflow GitHub Actions).
#   powershell -ExecutionPolicy Bypass -File tools\build_windows.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
python -m pip install -r requirements-dev.txt
python -m pytest -q
python tools\fetch_vosk_model.py
python tools\pregen_audio.py
python tools\write_version_info.py
python -m PyInstaller packaging\tcfmaster.spec --noconfirm --clean
$version = python -c "import tcfmaster; print(tcfmaster.__version__)"
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" "/DAppVersion=$version" packaging\installer.iss
Write-Host "Installateur : dist\installer\WhiteTekTCF-Setup-$version.exe"
