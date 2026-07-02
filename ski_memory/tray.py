"""Optional system-tray icon (open / quit).

Gives the windowless desktop app an always-available way to reopen or stop it,
so closing the browser tab isn't a trap. Best-effort: if pystray/Pillow aren't
available (or there's no display), make_tray returns None and the caller just
runs the server normally.
"""
from __future__ import annotations

import webbrowser


def make_tray(url: str, on_quit):
    """Return a pystray Icon (not yet run) or None if unavailable."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception:
        return None
    try:
        img = Image.new("RGBA", (64, 64), (20, 20, 23, 255))
        d = ImageDraw.Draw(img)
        d.polygon([(32, 8), (56, 32), (32, 56), (8, 32)], fill=(110, 231, 183, 255))
        d.polygon([(32, 20), (44, 32), (32, 44), (20, 32)], fill=(20, 20, 23, 255))

        def _open(icon, item):
            try:
                webbrowser.open(url)
            except Exception:
                pass

        def _quit(icon, item):
            try:
                icon.stop()
            finally:
                on_quit()

        menu = pystray.Menu(
            pystray.MenuItem("Open Continuum", _open, default=True),
            pystray.MenuItem("Quit", _quit),
        )
        return pystray.Icon("continuum", img, "Continuum", menu)
    except Exception:
        return None
