"""Local LLM access via Ollama (localhost only).

Talks to a local Ollama instance for conversation continuation. Makes no
internet calls — only 127.0.0.1. If Ollama isn't running or no model is
pulled, raises LLMUnavailable with actionable guidance.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from .ollama import detect

OLLAMA_CHAT = "http://127.0.0.1:11434/api/chat"


class LLMUnavailable(Exception):
    """Raised when no local model can serve a request."""


def available_models() -> list[str]:
    return detect().get("models", [])


def resolve_model(model: str | None = None) -> str:
    """Pick a usable model name or raise LLMUnavailable with guidance."""
    info = detect()
    if not info.get("available"):
        raise LLMUnavailable(
            "Ollama isn't running. Install it from https://ollama.com, then "
            "pull a model, e.g.  ollama pull llama3.2")
    model = model or (info["models"][0] if info.get("models") else None)
    if not model:
        raise LLMUnavailable(
            "Ollama is running but no model is installed. Pull one, e.g.  "
            "ollama pull llama3.2")
    return model


def chat(messages: list[dict], model: str | None = None, timeout: float = 180.0,
         num_predict: int = 512, temperature: float = 0.7, keep_alive: str = "30m") -> tuple[str, str]:
    """Send a chat completion to Ollama. Returns (reply_text, model_used)."""
    model = resolve_model(model)

    # keep_alive keeps the model resident in RAM between turns (no reload cost);
    # num_predict bounds reply length so CPU-only machines don't grind for minutes.
    payload = json.dumps({
        "model": model, "messages": messages, "stream": False,
        "keep_alive": keep_alive,
        "options": {"num_predict": num_predict, "temperature": temperature},
    }).encode()
    req = urllib.request.Request(
        OLLAMA_CHAT, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise LLMUnavailable(f"Local model call failed: {e}")
    except ValueError as e:
        raise LLMUnavailable(f"Unexpected response from Ollama: {e}")

    content = (data.get("message") or {}).get("content", "")
    if not content:
        raise LLMUnavailable("Local model returned an empty response.")
    return content, model


def chat_stream(messages: list[dict], model: str | None = None, timeout: float = 180.0,
                num_predict: int = 512, temperature: float = 0.7, keep_alive: str = "30m"):
    """Yield reply text chunks from Ollama as they are generated (stream=True).

    Resolves the model first (raises LLMUnavailable cleanly before any streaming
    begins). Connection errors mid-stream simply end the generator.
    """
    model = resolve_model(model)
    payload = json.dumps({
        "model": model, "messages": messages, "stream": True,
        "keep_alive": keep_alive,
        "options": {"num_predict": num_predict, "temperature": temperature},
    }).encode()
    req = urllib.request.Request(
        OLLAMA_CHAT, data=payload, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise LLMUnavailable(f"Local model call failed: {e}")
    with resp:
        for raw in resp:
            raw = raw.strip()
            if not raw:
                continue
            try:
                d = json.loads(raw.decode("utf-8"))
            except ValueError:
                continue
            chunk = (d.get("message") or {}).get("content", "")
            if chunk:
                yield chunk
            if d.get("done"):
                break


# --- model management (pull via Ollama's local API) -----------------------
import threading  # noqa: E402

OLLAMA_PULL = "http://127.0.0.1:11434/api/pull"

# Curated suggestions shown in the UI when no model is installed.
RECOMMENDED = [
    {"name": "llama3.2", "note": "~2 GB · small & fast, good first choice"},
    {"name": "qwen2.5:7b", "note": "~4.7 GB · stronger answers"},
    {"name": "mistral", "note": "~4.1 GB · balanced"},
    {"name": "nomic-embed-text", "note": "~274 MB · embeddings for semantic search"},
]

_pulls: dict[str, dict] = {}
_pulls_lock = threading.Lock()


def pull_status() -> dict:
    with _pulls_lock:
        return {k: dict(v) for k, v in _pulls.items()}


def start_pull(name: str) -> None:
    with _pulls_lock:
        cur = _pulls.get(name)
        if cur and not cur.get("done"):
            return  # already in progress
        _pulls[name] = {"status": "starting", "percent": 0, "done": False, "error": None}
    threading.Thread(target=_run_pull, args=(name,), daemon=True).start()


def _run_pull(name: str) -> None:
    try:
        payload = json.dumps({"name": name, "stream": True}).encode()
        req = urllib.request.Request(
            OLLAMA_PULL, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3600) as resp:
            for raw in resp:
                raw = raw.strip()
                if not raw:
                    continue
                d = json.loads(raw)
                status = d.get("status", "")
                total, completed = d.get("total"), d.get("completed")
                with _pulls_lock:
                    _pulls[name]["status"] = status
                    if total and completed:
                        _pulls[name]["percent"] = int(completed * 100 / total)
                    if status == "success":
                        _pulls[name].update({"done": True, "percent": 100})
        with _pulls_lock:
            if not _pulls[name]["done"]:
                _pulls[name].update({"done": True, "status": "success", "percent": 100})
    except Exception as e:  # noqa: BLE001
        with _pulls_lock:
            _pulls[name].update({"done": True, "error": str(e)})
