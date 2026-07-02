"""Command-line entry point.

    ski-memory            Start the local server and open the app in a browser.
    ski-memory --no-open  Start without opening a browser.
    ski-memory verify     Verify ledger integrity and exit.
    ski-memory info       Print store location and identity, then exit.
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import webbrowser

from .config import DEFAULT_HOST, DEFAULT_PORT, load_config


def _port_in_use(host: str, port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def _is_ski_memory(host: str, port: int) -> bool:
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=0.6) as r:
            return json.loads(r.read().decode("utf-8")).get("status") == "ok"
    except Exception:
        return False


def _find_free_port(host: str, start: int, span: int = 30) -> int:
    for p in range(start, start + span):
        if not _port_in_use(host, p):
            return p
    return start


def _cmd_verify() -> int:
    from .store import open_store

    store = open_store()
    ok, error = store.ledger.verify()
    if ok:
        print(f"OK — ledger verified ({len(store.ledger)} entries, chain intact).")
        return 0
    print(f"FAILED — {error}", file=sys.stderr)
    return 1


def _cmd_info() -> int:
    from .store import open_store

    store = open_store()
    print(f"SKI Memory data folder : {store.config.home}")
    print(f"Identity fingerprint   : {store.identity.fingerprint}")
    print(f"Public key             : {store.identity.public_key_hex}")
    print(f"Counts                 : {store.counts()}")
    return 0


def _serve(host: str, port: int, open_browser: bool) -> int:
    import uvicorn

    from .app import create_app

    # If the port is already taken, react gracefully.
    if _port_in_use(host, port):
        if _is_ski_memory(host, port):
            url = f"http://{host}:{port}"
            print(f"Continuum is already running at {url} — opening it in your browser.")
            if open_browser:
                try:
                    webbrowser.open(url)
                except Exception:
                    pass
            return 0
        new_port = _find_free_port(host, port + 1)
        print(f"Port {port} is in use; starting on {new_port} instead.")
        port = new_port

    config = load_config(host=host, port=port)
    # Start Ollama automatically if it's installed but not running.
    try:
        from . import ollama as _ollama
        threading.Thread(target=_ollama.ensure_running, daemon=True).start()
    except Exception:
        pass
    app = create_app(config)
    url = f"http://{host}:{port}"

    if open_browser:
        def _open():
            time.sleep(1.0)
            try:
                webbrowser.open(url)
            except Exception:
                pass

        threading.Thread(target=_open, daemon=True).start()

    print(f"Continuum — sovereign, local-first. Serving at {url}")
    print(f"Data folder: {config.home}  (nothing leaves this machine)")
    frozen = getattr(sys, "frozen", False)
    cfg_kwargs = {"host": host, "port": port, "log_level": "info"}
    if frozen:
        # No console in the packaged app: skip uvicorn's stream-based log config.
        cfg_kwargs["log_config"] = None
        cfg_kwargs["access_log"] = False
    server = uvicorn.Server(uvicorn.Config(app, **cfg_kwargs))

    from . import tray as tray_mod

    def _stop_everything():
        server.should_exit = True
        os._exit(0)

    icon = tray_mod.make_tray(url, _stop_everything) if open_browser else None
    if icon is not None:
        # Server in a worker thread; tray icon owns the main thread (blocks until Quit).
        threading.Thread(target=server.run, daemon=True).start()
        try:
            icon.run()
        except Exception:
            server.run()
    else:
        server.run()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ski-memory", description="SKI Memory")
    parser.add_argument("command", nargs="?", default="serve",
                        choices=["serve", "verify", "info"])
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-open", action="store_true",
                        help="do not open a browser window")
    args = parser.parse_args(argv)

    if args.command == "verify":
        return _cmd_verify()
    if args.command == "info":
        return _cmd_info()
    return _serve(args.host, args.port, open_browser=not args.no_open)


if __name__ == "__main__":
    raise SystemExit(main())
