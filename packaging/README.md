# Packaging SKI Memory into a one-click app

These scripts bundle SKI Memory into a single executable that a user can
download and double-click — no Python, no terminal, no `pip install`.

## Build it (on the OS you want to ship to)

PyInstaller does **not** cross-compile: build the Windows `.exe` on Windows,
the macOS app on a Mac, the Linux binary on Linux.

From the `ski-memory/` folder:

**Windows**

```powershell
.\packaging\build.ps1
```

or double-click `packaging\build.bat`.

**macOS / Linux**

```bash
pip install pyinstaller
python packaging/build.py
```

The result lands in `dist/`:
- Windows → `dist\Continuum.exe`
- macOS/Linux → `dist/Continuum`

Double-clicking it starts the local server and opens the app in the browser at
`http://127.0.0.1:8765`. A small console window shows the URL and logs (set
`console=False` in `ski_memory.spec` for a windowless app).

## What's bundled

- The full Python runtime and all dependencies (FastAPI, uvicorn, cryptography).
- The web UI assets (`ski_memory/web/`), via `collect_data_files`.
- The app resolves these from `sys._MEIPASS` when frozen (see `app.py`).

The user's data still lives in their own `~/.ski_memory` folder, created on
first run — the executable is just the program, not the data.

## Make a real installer (and install Ollama for the user)

The bare `Continuum.exe` runs standalone, but for distribution you want a proper
installer with a Start-menu entry, a desktop shortcut, an uninstaller — and one
that sets up the only external dependency, **Ollama** (the Python libraries are
already inside the exe; chat/embedding models are downloaded inside the app).

`installer.iss` (Inno Setup) does all of this:

1. Build the exe first: `python packaging\build.py` → `dist\Continuum.exe`.
2. Install **Inno Setup 6.1+** from https://jrsoftware.org/isinfo.php.
3. Compile the script: open `packaging\installer.iss` in Inno Setup and click
   **Compile**, or run `iscc packaging\installer.iss`.
4. Output: `packaging\Output\Continuum-Setup.exe` — the file you distribute.

During setup the user gets a checked task **"Install Ollama …"**. If Ollama
isn't already on the machine, the installer downloads the official
`OllamaSetup.exe` and runs it silently (`/SILENT`), so the user doesn't have to
visit a website. (Needs internet during install; if it fails, Continuum still
installs and the app guides them to ollama.com.) After install, the user picks
and downloads a model from inside Continuum (the hardware-matched recommendation).

## Notes & next steps

- **Memory:** PyInstaller's analysis step is RAM-hungry; build on a machine
  with several GB free.
- **Antivirus / SmartScreen:** unsigned executables may trigger a warning on
  first run. For public distribution, code-sign the binary (Windows
  Authenticode / Apple notarization).
- **Installer (optional):** to get a real installer rather than a bare exe,
  wrap `dist\Continuum.exe` with Inno Setup or NSIS (Windows) or build a
  `.dmg` (macOS). The bare executable already runs standalone.
- **Distribution:** upload the built binary to GitHub Releases (matches the
  download-analytics plan).
