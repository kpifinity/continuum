# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — builds a single-file SKI Memory executable.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Bundle the web/ assets that ship inside the ski_memory package.
datas = collect_data_files("ski_memory")
# uvicorn loads protocol/loop implementations dynamically.
hiddenimports = (collect_submodules("uvicorn") + collect_submodules("anyio")
                 + collect_submodules("pystray") + ["ski_memory", "PIL.Image", "PIL.ImageDraw"])

a = Analysis(
    ["run_ski_memory.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "PIL"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Continuum",
    icon="icon.ico",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,           # windowed app (no terminal); quit via the in-app Quit button
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
