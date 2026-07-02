@echo off
REM Build the SKI Memory Windows executable.
python -m pip install --upgrade pyinstaller
python packaging\build.py
echo If it built, your app is at dist\Continuum.exe
pause
