"""System checker + hardware-based model recommendations.

Detects the machine's OS, CPU, RAM and (best-effort) GPU/VRAM, then recommends
local models in three tiers — Fast, Recommended, and Max quality — with a
feasibility flag based on available memory. Helps users pick a model that will
actually run well on their computer. All local; no network.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess


# --- detection ------------------------------------------------------------
def _total_ram_bytes() -> int:
    # Linux / macOS
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, AttributeError, OSError):
        pass
    # Windows
    try:
        import ctypes

        class _MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        ms = _MS()
        ms.dwLength = ctypes.sizeof(_MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))  # type: ignore[attr-defined]
        return int(ms.ullTotalPhys)
    except Exception:
        return 0


def _detect_gpu() -> dict | None:
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run(
                [smi, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=4)
            if out.returncode == 0:
                vals = [int(x) for x in out.stdout.split() if x.strip().isdigit()]
                if vals:
                    return {"vendor": "NVIDIA", "vram_gb": round(max(vals) / 1024, 1),
                            "unified": False}
        except Exception:
            pass
    return None


def detect() -> dict:
    sysname = platform.system()
    machine = platform.machine()
    apple = sysname == "Darwin" and machine.lower() in ("arm64", "aarch64")
    ram_gb = _total_ram_bytes() / 1e9
    gpu = _detect_gpu()
    if gpu is None and apple:
        # Apple Silicon shares memory between CPU and GPU.
        gpu = {"vendor": "Apple Silicon", "vram_gb": round(ram_gb * 0.7, 1), "unified": True}
    return {
        "os": sysname or "unknown", "arch": machine or "unknown",
        "cpu_count": os.cpu_count() or 0, "ram_gb": round(ram_gb, 1),
        "apple_silicon": apple, "gpu": gpu,
    }


# --- recommendation -------------------------------------------------------
def recommend(info: dict) -> dict:
    ram = info.get("ram_gb") or 0.0
    gpu = info.get("gpu")
    has_dedicated_gpu = bool(gpu and not gpu.get("unified"))
    mem = (gpu.get("vram_gb") if gpu and gpu.get("vram_gb") else ram) or 0.0
    if gpu and gpu.get("unified"):
        accel = "Apple GPU (unified memory)"
    elif has_dedicated_gpu:
        accel = f"{gpu['vendor']} GPU"
    else:
        accel = "CPU only"

    fast = ("llama3.2", "3B · fast and light, runs on almost anything", 4)

    if mem >= 12:
        rec = ("qwen2.5:7b", "7B · strong all-round quality", 6)
    elif mem >= 8:
        rec = ("llama3.1:8b", "8B · solid quality", 6)
    else:
        rec = ("llama3.2", "3B · the best your memory supports comfortably", 4)

    if mem >= 42:
        mx = ("llama3.3:70b", "70B · top quality, needs lots of memory", 42)
    elif mem >= 20:
        mx = ("qwen2.5:32b", "32B · excellent quality", 20)
    elif mem >= 12:
        mx = ("qwen2.5:14b", "14B · high quality, slower", 10)
    else:
        mx = rec  # hardware-limited: max == recommended

    def card(tier, t, desc):
        name, note, req = t
        return {"tier": tier, "name": name, "note": note, "min_ram_gb": req,
                "feasible": mem >= req, "comfortable": mem >= req * 1.4,
                "detail": desc}

    cards = [
        card("Fast", fast, "Lowest latency; great for quick back-and-forth."),
        card("Recommended", rec, "Best balance of quality and speed for your machine."),
        card("Max quality", mx,
             "Highest quality this machine can handle"
             + (" — expect slower replies." if accel == "CPU only" else ".")),
    ]
    note = None
    if mx[0] == rec[0]:
        note = "Your memory limits the largest model, so Recommended and Max are the same."
    elif accel == "CPU only":
        note = "No dedicated GPU detected — larger models will run but more slowly."

    return {"accelerator": accel, "effective_memory_gb": round(mem, 1),
            "cards": cards, "note": note}
