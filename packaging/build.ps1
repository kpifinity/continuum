# Build the SKI Memory Windows executable.
# Usage (PowerShell, from the ski-memory folder):
#   .\packaging\build.ps1
python -m pip install --upgrade pyinstaller
python packaging\build.py
Write-Host "If it built, your app is at dist\Continuum.exe"
