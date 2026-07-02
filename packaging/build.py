#!/usr/bin/env python3
"""Build a single-file SKI Memory executable with PyInstaller.

Usage:
    pip install pyinstaller
    python packaging/build.py

The binary is written to dist/ (SKI-Memory.exe on Windows, SKI-Memory elsewhere).
Run this on the OS you want to target — PyInstaller does not cross-compile.
"""
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = pathlib.Path(__file__).resolve().parent / "ski_memory.spec"


def main() -> int:
    os.chdir(ROOT)
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Run:  pip install pyinstaller")
        return 1
    cmd = [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", str(SPEC)]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    out = ROOT / "dist"
    print(f"\nDone. Find your app in: {out}")
    print("On Windows it's dist\\Continuum.exe — double-click to run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
