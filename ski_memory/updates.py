"""Update check — the only outbound call Continuum makes by default.

Fetches a tiny static manifest from skiframework.org, compares it to the running
version, and (best-effort) reads the LOCAL Ollama version so Ollama updates can
be surfaced through Continuum too. It is a plain GET that sends no app data, no
identifiers, and no chat content. Controlled by a user toggle (on by default),
results cached for half a day. Never raises; never blocks the app meaningfully.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__

MANIFEST_URL = os.environ.get(
    "CONTINUUM_UPDATE_URL", "https://skiframework.org/continuum/latest.json")
DOWNLOAD_URL = "https://skiframework.org/continuum"
OLLAMA_VERSION_URL = "http://127.0.0.1:11434/api/version"
CHECK_INTERVAL = 12 * 60 * 60  # at most twice a day
_TIMEOUT = 4.0


def _state_path(home: Path) -> Path:
    return Path(home) / "updates.json"


def _read(home: Path) -> dict:
    try:
        return json.loads(_state_path(home).read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _write(home: Path, data: dict) -> None:
    try:
        _state_path(home).write_text(json.dumps(data, indent=2), "utf-8")
    except OSError:
        pass


def _parse_ver(v: str) -> tuple:
    """Lenient semver -> tuple of ints. '0.2.0-beta' -> (0, 2, 0). Suffixes ignored."""
    out = []
    for part in str(v or "").split("."):
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        out.append(int(digits) if digits else 0)
    return tuple(out) or (0,)


def _newer(a: str, b: str) -> bool:
    """True if version a is strictly newer than b."""
    pa, pb = _parse_ver(a), _parse_ver(b)
    n = max(len(pa), len(pb))
    pa += (0,) * (n - len(pa))
    pb += (0,) * (n - len(pb))
    return pa > pb


def settings(home: Path) -> dict:
    st = _read(home)
    return {"check_enabled": st.get("check_enabled", True)}


def set_check_enabled(home: Path, enabled: bool) -> dict:
    st = _read(home)
    st["check_enabled"] = bool(enabled)
    _write(home, st)
    return settings(home)


def _ollama_version() -> str | None:
    try:
        with urllib.request.urlopen(OLLAMA_VERSION_URL, timeout=1.5) as r:
            return (json.loads(r.read().decode("utf-8")) or {}).get("version")
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def _fetch_manifest() -> dict:
    req = urllib.request.Request(MANIFEST_URL, headers={"User-Agent": "Continuum"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _empty_result() -> dict:
    return {"current": __version__, "latest": "", "app_update_available": False,
            "notes": "", "url": DOWNLOAD_URL, "ollama_current": None,
            "ollama_recommended": "", "ollama_update_available": False,
            "ollama_url": "https://ollama.com/download"}


def check(home: Path, force: bool = False) -> dict:
    """Return the latest known update status, refreshing from the network if the
    cache is stale and checking is enabled. Best-effort; falls back to cache."""
    st = _read(home)
    enabled = st.get("check_enabled", True)
    now = time.time()
    if enabled and (force or now - float(st.get("last_check") or 0) > CHECK_INTERVAL):
        try:
            m = _fetch_manifest()
            latest = m.get("version") or ""
            oll = _ollama_version()
            oll_rec = m.get("ollama_recommended") or ""
            result = {
                "current": __version__,
                "latest": latest,
                "app_update_available": bool(latest) and _newer(latest, __version__),
                "notes": m.get("notes", ""),
                "url": m.get("url") or DOWNLOAD_URL,
                "ollama_current": oll,
                "ollama_recommended": oll_rec,
                "ollama_update_available": bool(oll and oll_rec and _newer(oll_rec, oll)),
                "ollama_url": m.get("ollama_url") or "https://ollama.com/download",
            }
            st["last_result"] = result
            st["last_check"] = now
            _write(home, st)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            pass
    res = dict(st.get("last_result") or _empty_result())
    res["check_enabled"] = enabled
    return res
