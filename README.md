# Continuum

*Built on the [SKI Framework](https://skiframework.org).*

**Never stop mid-thought.** When you hit your Claude/ChatGPT usage limit, Continuum keeps you going locally with full context — then hands you back to the cloud model when it's ready. Import your history into a local, verifiable knowledge graph, search everything, ask across your whole archive, and continue any thread on your own machine with a local model. **Nothing leaves your computer.**

### The bridge

- **Bridge in a conversation** — paste a Claude transcript (or an export JSON) and continue it locally the moment you're rate-limited.
- **Resume in Claude** — when the cloud model is back, generate a concise handoff brief to paste in so it picks up exactly where you left off.

Built on the principles of the [SKI Framework](https://skiframework.org) (Sovereign Knowledge Intelligence): a sovereign, local-first design, an Ed25519-signed knowledge graph, a hash-chained tamper-evident ledger, and provenance on every node.

> Status: **v0.1 — end-to-end POC.** The sovereign core plus a working import → knowledge-graph → search → view loop. Rough edges expected; polish, packaging, and local continuation come next. Local LLM (Ollama) is optional and detected automatically.

## What works today

- A local, per-user **app-data store** (SQLite) created on first run — entirely on your machine.
- A device **cryptographic identity** (Ed25519 keypair) generated and stored locally.
- A **hash-chained, append-only ledger** that signs every event (imports, KG builds) and can prove it hasn't been tampered with.
- **Importers** for Claude, ChatGPT, and a generic/Grok JSON format, with idempotent re-import.
- A first-pass **structural knowledge graph** (conversation, link, code-block, and entity nodes) with a provenance envelope on every node — no LLM required.
- **Search** across every imported conversation, a **conversation viewer**, and a per-conversation **KG panel**.
- **Continue any thread locally** with your own model via Ollama — new messages are written back into the store with provenance and recorded in the ledger. Works only with a local model; no cloud.
- **GraphRAG context**: continuation retrieves relevant passages from across *all* your conversations and feeds them to the local model, so it answers with your broader memory in view. The conversations it drew from are shown under the reply and recorded in the ledger.
- **Semantic retrieval (optional)**: build an embedding index (via a local embedding model such as `nomic-embed-text`, downloadable in-app) and continuation retrieval ranks context by *meaning* — catching paraphrases, not just shared words. Falls back to lexical matching automatically when no index/model is present.
- **System checker**: detects your RAM/CPU/GPU and recommends models in three tiers — Fast, Recommended, and Max quality — each marked feasible for your hardware and downloadable in one click.
- **Ask your memory**: a single question answered from across *all* your conversations at once — the app retrieves the most relevant passages (semantic or lexical) and the local model composes an answer with cited sources. Fully local.
- **Compare answers (automatic)**: Continuum scans your imported chats and finds where you asked the *same question in more than one place* (semantic when the embedding index exists, lexical otherwise), shows the answers side by side, and the local model consolidates the consensus, the conflicts, and a single best answer. Manual compare is still available too.
- **My Memory**: a curated, user-owned knowledge base (signed + ledgered), separate from raw chats. Save consolidations or notes; Memory is weighted above raw conversations when answering.
- **Verifiable thread export** — export any conversation as a signed, self-contained `*.skimem.json` bundle (messages + KG + related ledger entries + Ed25519 signature). Anyone can verify it offline with `tools/verify_ski_export.py` — no SKI Memory install required.
- A **FastAPI** app + single-page UI; **zero outbound network connections** at runtime by default (local model calls go only to `127.0.0.1`).

## Continue a conversation locally (optional, needs Ollama)

1. Install **Ollama** from https://ollama.com and start it.
2. On the SKI Memory home screen, use **Manage local models** to download a model
   (e.g. `llama3.2`) with one click — no terminal needed. (Or `ollama pull llama3.2` if you prefer.)
3. Open any conversation, pick the model in the composer's dropdown, and type in the
   **Continue this thread locally** box at the bottom.

Without Ollama the rest of the app works fully; the composer just shows setup guidance.

## Verify an exported thread (no app needed)

Open any conversation and click **Export · verifiable** to download a `*.skimem.json` bundle.
Anyone can then check it is authentic and unaltered, fully offline:

```bash
pip install cryptography
python tools/verify_ski_export.py thread.skimem.json
```

It reports PASS/FAIL on three checks: message integrity (SHA-256), the Ed25519 export
signature, and the authenticity of the bundled ledger entries.

## Try it with the bundled samples

After launching, click **+ Import export** (top right) and choose any file from the `examples/` folder
(`claude_export.json`, `chatgpt_export.json`, `grok_export.json`) to see the full loop.

## Quick start

Requires Python 3.10+.

```bash
# from the ski-memory/ folder
pip install -e .
ski-memory
```

This starts the local server and opens the app in your browser at `http://127.0.0.1:8765`.

To run without installing:

```bash
pip install fastapi "uvicorn[standard]" cryptography
python -m ski_memory
```

## Where your data lives

Everything is stored in a single folder you own:

- macOS / Linux: `~/.ski_memory/`
- Windows: `%USERPROFILE%\.ski_memory\`
- Override with the `SKI_MEMORY_HOME` environment variable.

That folder holds your SQLite database (`ski_memory.db`), your identity key (`identity.key`, created `0600`), and your public key (`identity.pub`).

## Verify ledger integrity

```bash
python -m ski_memory verify
```

Recomputes the entire hash chain and checks every signature. Any alteration to any past entry breaks the chain and fails verification.

## Sovereignty

By design, SKI Memory makes no outbound internet connections during normal operation. Local model inference (later milestones) talks only to a local Ollama instance on `127.0.0.1`. A no-outbound test is part of the suite.

## License

Apache-2.0. "SKI Framework", "Sovereign Knowledge Intelligence" are trademarks of KpiFinity Inc.
