"""Opt-in, anonymous, privacy-preserving usage counting.

Continuum is sovereign: by default it makes NO internet connections. This module
is the single, deliberate exception, and only ever runs with the user's explicit
consent.

What it can send (only when consent is True):
  - a random install id (uuid4) generated on this machine — not tied to identity,
    email, files, or anything personal
  - the event name ("install" or "heartbeat")
  - the app version, OS family and CPU arch (coarse, e.g. "Windows"/"AMD64")

What it NEVER sends: chat content, titles, prompts, file paths, the crypto
identity/fingerprint, IP-identifying data we control, or anything a user typed.

Consent states:
  - None  -> undecided; the UI shows a one-time prompt. Nothing is sent.
  - False -> declined; nothing is ever sent.
  - True  -> granted; an "install" ping fires once, then a daily "heartbeat".

All network calls are best-effort, short-timeout, on a daemon thread, and
swallow every error — analytics can never block or break the app.
"""
from __future__ import annotations

import json
import os
import platform
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from . import __version__

# Where pings go. Override with CONTINUUM_ANALYTICS_URL. The default points at
# kpifinity.com, where a tiny counter endpoint must be deployed (see
# analytics-server/ in the repo). If the endpoint is absent, pings simply fail
# silently — the app is unaffected.
ENDPOINT = os.environ.get(
    "CONTINUUM_ANALYTICS_URL", "https://kpifinity.com/api/continuum/ping")

HEARTBEAT_INTERVAL = 24 * 60 * 60  # at most one heartbeat per day
_PING_TIMEOUT = 4.0


def _state_path(home: Path) -> Path:
    return Path(home) / "analytics.json"


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


def load(home: Path) -> dict:
    """Return analytics state, generating a stable install id on first use.

    Shape: {install_id, consent: bool|None, install_sent: bool, last_heartbeat: float}
    """
    data = _read(home)
    changed = False
    if not data.get("install_id"):
        data["install_id"] = uuid.uuid4().hex
        changed = True
    if "consent" not in data:
        data["consent"] = True  # on by default (opt-out); user can disable in Settings
        changed = True
    if changed:
        _write(home, data)
    return data


def public_state(home: Path) -> dict:
    """State safe to expose to the local UI (no need to hide the id, but we don't)."""
    d = load(home)
    return {"consent": d.get("consent"), "decided": d.get("consent") is not None}


def set_consent(home: Path, consent: bool) -> dict:
    data = load(home)
    data["consent"] = bool(consent)
    _write(home, data)
    if consent:
        # Fire the one-time install ping immediately (background, best-effort).
        send(home, "install")
    return public_state(home)


def _payload(install_id: str, event: str) -> bytes:
    return json.dumps({
        "install_id": install_id,
        "event": event,
        "app": "continuum",
        "version": __version__,
        "os": platform.system() or "unknown",
        "arch": platform.machine() or "unknown",
        "ts": int(time.time()),
    }).encode("utf-8")


def _post(payload: bytes) -> None:
    try:
        req = urllib.request.Request(
            ENDPOINT, data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "Continuum"})
        urllib.request.urlopen(req, timeout=_PING_TIMEOUT).close()
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        pass  # best-effort only; never surfaces


def send(home: Path, event: str) -> None:
    """Send a ping on a daemon thread IF the user has consented. No-op otherwise."""
    data = load(home)
    if data.get("consent") is not True:
        return
    payload = _payload(data["install_id"], event)
    threading.Thread(target=_post, args=(payload,), daemon=True).start()


def startup(home: Path) -> None:
    """On launch: if analytics is enabled (on by default), send a one-time
    'install' ping, then a daily 'heartbeat' thereafter. Opt-out via Settings."""
    data = load(home)
    if data.get("consent") is not True:
        return
    if not data.get("install_sent"):
        data["install_sent"] = True
        _write(home, data)
        threading.Thread(
            target=_post, args=(_payload(data["install_id"], "install"),), daemon=True).start()
    else:
        heartbeat(home)


def heartbeat(home: Path) -> None:
    """Send at most one 'heartbeat' per day, for active-user counting. Consent-gated."""
    data = load(home)
    if data.get("consent") is not True:
        return
    now = time.time()
    if now - float(data.get("last_heartbeat") or 0) < HEARTBEAT_INTERVAL:
        return
    data["last_heartbeat"] = now
    _write(home, data)
    threading.Thread(
        target=_post, args=(_payload(data["install_id"], "heartbeat"),), daemon=True).start()
