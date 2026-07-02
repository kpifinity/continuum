"""FastAPI application: the local SKI Memory server."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, analytics, updates, ask as ask_mod, bridge, continuation, embeddings, export, ingest, kg, llm, memgraph, memory as memory_mod, ollama, overlaps as overlaps_mod, sysinfo
from .config import Config, load_config
from .store import Store

# When packaged with PyInstaller, data files live under sys._MEIPASS.
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    WEB_DIR = Path(sys._MEIPASS) / "ski_memory" / "web"
else:
    WEB_DIR = Path(__file__).parent / "web"


class ImportBody(BaseModel):
    filename: str = ""
    content: str


class ContinueBody(BaseModel):
    message: str
    model: str | None = None


class AskBody(BaseModel):
    question: str
    model: str | None = None


class ConsolidateBody(BaseModel):
    question: str
    answers: list[dict]
    model: str | None = None


class MemoryBody(BaseModel):
    title: str
    body: str
    tags: list[str] | None = None
    provenance: dict | None = None


class MemEditBody(BaseModel):
    target: str
    op: str
    value: object | None = None


class PasteBody(BaseModel):
    text: str
    title: str | None = None
    source: str | None = None


class BriefBody(BaseModel):
    model: str | None = None


class ConsentBody(BaseModel):
    consent: bool


class UpdateSettingsBody(BaseModel):
    check_enabled: bool


def create_app(config: Config | None = None) -> FastAPI:
    config = config or load_config()
    store = Store(config)

    app = FastAPI(title="Continuum", version=__version__)
    app.state.store = store
    app.state.config = config

    # Anonymous, opt-in usage counting. Consent-gated; no-op unless the user
    # has explicitly agreed. Fires a daily heartbeat in the background.
    try:
        analytics.startup(config.home)
    except Exception:
        pass

    @app.middleware("http")
    async def _no_cache_static(request, call_next):
        resp = await call_next(request)
        if request.url.path.startswith("/static") or request.url.path == "/":
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/api/status")
    def status() -> dict:
        ok, error = store.ledger.verify()
        head = store.ledger.head()
        return {
            "version": __version__, "sovereign": True, "outbound_connections": 0,
            "home": str(config.home),
            "identity": {"fingerprint": store.identity.fingerprint,
                         "public_key": store.identity.public_key_hex},
            "counts": store.counts(),
            "ledger": {"entries": len(store.ledger), "verified": ok, "error": error,
                       "head_hash": head.entry_hash if head else None},
            "ollama": ollama.detect(),
        }

    @app.post("/api/import")
    def do_import(body: ImportBody) -> dict:
        try:
            summary = ingest.import_into_store(store, body.content, body.filename)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"Import failed: {e}")
        kg_summary = kg.build_all(store)
        return {"import": summary, "kg": kg_summary, "counts": store.counts()}

    @app.get("/api/conversations")
    def conversations() -> dict:
        rows = store.conn.execute(
            "SELECT c.id, c.title, c.source, c.created_at, "
            "(SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) "
            "FROM conversations c ORDER BY c.imported_at DESC").fetchall()
        return {"conversations": [
            {"id": r[0], "title": r[1], "source": r[2],
             "created_at": r[3], "messages": r[4]} for r in rows]}

    @app.get("/api/conversations/{conversation_id}")
    def conversation(conversation_id: str) -> dict:
        c = store.conn.execute(
            "SELECT id, title, source FROM conversations WHERE id=?",
            (conversation_id,)).fetchone()
        if not c:
            raise HTTPException(status_code=404, detail="Not found")
        msgs = store.conn.execute(
            "SELECT seq, role, model, content, created_at, meta FROM messages "
            "WHERE conversation_id=? ORDER BY seq", (conversation_id,)).fetchall()
        return {
            "conversation": {"id": c[0], "title": c[1], "source": c[2]},
            "messages": [{"seq": m[0], "role": m[1], "model": m[2],
                          "content": m[3], "created_at": m[4],
                          "local": (m[5] or "").find("local_continuation") >= 0}
                         for m in msgs],
            "graph": kg.graph_for_conversation(store, conversation_id),
        }

    @app.post("/api/conversations/{conversation_id}/continue")
    def do_continue(conversation_id: str, body: ContinueBody) -> dict:
        if not body.message.strip():
            raise HTTPException(status_code=400, detail="Empty message")
        try:
            return continuation.continue_conversation(
                store, conversation_id, body.message, body.model)
        except continuation.ConversationNotFound:
            raise HTTPException(status_code=404, detail="Conversation not found")
        except llm.LLMUnavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.post("/api/conversations/{conversation_id}/continue/stream")
    def do_continue_stream(conversation_id: str, body: ContinueBody):
        if not body.message.strip():
            raise HTTPException(status_code=400, detail="Empty message")
        try:
            gen = continuation.stream_continue(
                store, conversation_id, body.message, body.model)
        except continuation.ConversationNotFound:
            raise HTTPException(status_code=404, detail="Conversation not found")
        except llm.LLMUnavailable as e:
            raise HTTPException(status_code=503, detail=str(e))
        return StreamingResponse(gen, media_type="application/x-ndjson")

    @app.get("/api/conversations/{conversation_id}/export")
    def export_conversation(conversation_id: str) -> Response:
        try:
            bundle = export.build_export(store, conversation_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Conversation not found")
        import json as _json
        data = _json.dumps(bundle, indent=2, ensure_ascii=False)
        fname = conversation_id.replace(":", "_").replace("/", "_") + ".skimem.json"
        return Response(content=data, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})

    @app.post("/api/verify-export")
    def verify_export_endpoint(bundle: dict) -> dict:
        ok, checks = export.verify_export(bundle)
        return {"verified": ok, "checks": checks}

    @app.get("/api/models")
    def models() -> dict:
        info = ollama.detect()
        return {"available": info["available"], "installed": info["models"],
                "recommended": llm.RECOMMENDED, "pulls": llm.pull_status()}

    @app.post("/api/models/pull")
    def pull_model(body: dict) -> dict:
        name = (body.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Missing model name")
        if not ollama.detect()["available"]:
            raise HTTPException(status_code=503,
                detail="Ollama isn't running. Install it from https://ollama.com and start it.")
        llm.start_pull(name)
        return {"started": True, "name": name}

    @app.get("/api/models/pull-status")
    def models_pull_status() -> dict:
        return {"pulls": llm.pull_status()}

    @app.get("/api/system")
    def system_info() -> dict:
        info = sysinfo.detect()
        rec = sysinfo.recommend(info)
        installed = ollama.detect().get("models", [])
        def _norm(n): return n[:-7] if n.endswith(":latest") else n
        inst = {_norm(m) for m in installed}
        for c in rec["cards"]:
            c["installed"] = _norm(c["name"]) in inst
        return {"system": info, "recommendation": rec, "ollama": ollama.detect()["available"]}

    @app.get("/api/embeddings/status")
    def embeddings_status() -> dict:
        return embeddings.status(store)

    @app.post("/api/embeddings/build")
    def embeddings_build(body: dict | None = None) -> dict:
        model = (body or {}).get("model") or embeddings.DEFAULT_MODEL
        if not ollama.detect()["available"]:
            raise HTTPException(status_code=503, detail="Ollama isn't running.")
        if not embeddings.model_available(model):
            raise HTTPException(status_code=400,
                detail=f"Embedding model '{model}' not installed. Download it first (Manage local models).")
        embeddings.build_index(store, model)
        return {"started": True, "model": model}

    @app.post("/api/paste")
    def paste_conversation(body: PasteBody) -> dict:
        if not body.text.strip():
            raise HTTPException(status_code=400, detail="Nothing pasted")
        summary, ids = bridge.ingest_pasted(store, body.text, body.title, body.source)
        kg.build_all(store)
        return {"summary": summary, "conversation_ids": ids, "counts": store.counts()}

    @app.post("/api/conversations/{conversation_id}/handoff-brief")
    def handoff_brief(conversation_id: str, body: BriefBody | None = None) -> dict:
        try:
            return bridge.make_brief(store, conversation_id, body.model if body else None)
        except ValueError:
            raise HTTPException(status_code=404, detail="Conversation not found")

    @app.get("/api/overlaps")
    def overlaps_list() -> dict:
        return {"overlaps": overlaps_mod.find_overlaps(store)}

    @app.post("/api/consolidate")
    def do_consolidate(body: ConsolidateBody) -> dict:
        if not body.question.strip() or len(body.answers) < 1:
            raise HTTPException(status_code=400, detail="Need a question and at least one answer")
        try:
            return memory_mod.consolidate(store, body.question, body.answers, body.model)
        except llm.LLMUnavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.get("/api/memory")
    def memory_list() -> dict:
        return {"entries": memory_mod.list_entries(store)}

    @app.post("/api/memory")
    def memory_add(body: MemoryBody) -> dict:
        if not body.title.strip() or not body.body.strip():
            raise HTTPException(status_code=400, detail="Title and body required")
        return memory_mod.add_entry(store, body.title, body.body, body.tags, body.provenance)

    @app.get("/api/memory/search")
    def memory_search(q: str = "") -> dict:
        return {"results": memory_mod.search(store, q)}

    @app.get("/api/memory/graph")
    def memory_graph(type: str | None = None, provider: str | None = None,
                     limit: int = 60) -> dict:
        return memgraph.build_global_graph(store, type, provider, limit)

    @app.get("/api/memory/node")
    def memory_node(id: str) -> dict:
        return memgraph.node_detail(store, id)

    @app.post("/api/memory/edit")
    def memory_edit(body: MemEditBody) -> dict:
        try:
            return memgraph.edit(store, body.target, body.op, body.value)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/ask")
    def do_ask(body: AskBody) -> dict:
        if not body.question.strip():
            raise HTTPException(status_code=400, detail="Empty question")
        try:
            return ask_mod.ask(store, body.question, body.model)
        except llm.LLMUnavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.post("/api/ask/stream")
    def do_ask_stream(body: AskBody):
        if not body.question.strip():
            raise HTTPException(status_code=400, detail="Empty question")
        try:
            gen = ask_mod.stream_ask(store, body.question, body.model)
        except llm.LLMUnavailable as e:
            raise HTTPException(status_code=503, detail=str(e))
        return StreamingResponse(gen, media_type="application/x-ndjson")

    @app.get("/api/analytics")
    def analytics_state() -> dict:
        return analytics.public_state(config.home)

    @app.post("/api/analytics/consent")
    def analytics_consent(body: ConsentBody) -> dict:
        return analytics.set_consent(config.home, body.consent)

    @app.get("/api/updates")
    def updates_check() -> dict:
        return updates.check(config.home)

    @app.post("/api/updates/settings")
    def updates_settings(body: UpdateSettingsBody) -> dict:
        return updates.set_check_enabled(config.home, body.check_enabled)

    @app.post("/api/quit")
    def quit_app() -> dict:
        import os
        import threading
        import time

        def _die():
            time.sleep(0.3)
            os._exit(0)
        threading.Thread(target=_die, daemon=True).start()
        return {"quitting": True}

    @app.get("/api/search")
    def search(q: str = "") -> dict:
        return {"query": q, "results": kg.search(store, q)}

    @app.get("/api/ledger/verify")
    def ledger_verify() -> dict:
        ok, error = store.ledger.verify()
        return {"verified": ok, "error": error, "entries": len(store.ledger)}

    if (WEB_DIR / "static").exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/favicon.ico")
    def favicon() -> JSONResponse:
        return JSONResponse({}, status_code=204)

    return app
