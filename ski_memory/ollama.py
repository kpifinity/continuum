"""Optional local-LLM detection.

SKI Memory works fully without any LLM. If a local Ollama instance is running
on 127.0.0.1, later milestones use it for semantic extraction and local
continuation. This module only *detects* it — it makes no internet calls.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434/api/tags"


def detect(timeout: float = 0.4) -> dict:
    """Return Ollama availability and any installed model names.

    Connects only to localhost. Never raises.
    """
    try:
        with urllib.request.urlopen(OLLAMA_URL, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = [m.get("name") for m in data.get("models", []) if m.get("name")]
        return {"available": True, "models": models}
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return {"available": False, "models": []}


def _ollama_exe():
    import os
    import shutil
    p = shutil.which("ollama")
    if p:
        return p
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\\Programs\\Ollama\\ollama.exe"),
        r"C:\\Program Files\\Ollama\\ollama.exe",
        "/usr/local/bin/ollama", "/opt/homebrew/bin/ollama",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def ensure_running(timeout: float = 8.0) -> bool:
    """If Ollama is installed but not responding, start it. Returns True if up."""
    import os
    import subprocess
    import time
    if detect(0.4).get("available"):
        return True
    exe = _ollama_exe()
    if not exe:
        return False
    try:
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=flags)
    except Exception:
        return False
    t0 = time.time()
    while time.time() - t0 < timeout:
        if detect(0.4).get("available"):
            return True
        time.sleep(0.5)
    return False
