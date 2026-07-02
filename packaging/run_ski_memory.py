"""Frozen entry point for the packaged Continuum app.

Double-clicking the built binary runs the local server and opens the browser.
In a windowless build sys.stdout/sys.stderr are None, which breaks libraries
that probe the stream (e.g. uvicorn's log formatter calls .isatty()), so we
point them at the null device first.
"""
import multiprocessing
import os
import sys

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from ski_memory.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # required for frozen apps on Windows
    raise SystemExit(main())
