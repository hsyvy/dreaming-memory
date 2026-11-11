"""Dreaming — a Hermes memory provider built on the architecture in Anthropic's
"The components of agent memory" (https://www.anthropic.com/research/components-of-agent-memory).

In a session the provider records the transcript, gives the agent a small memory folder to
write notes in, injects a capped index, and recalls related pages for each message. Between
sessions a dream pass (``dream.py``) checks notes against the transcripts, builds a linked
wiki and keeps the index small. Everything is local files plus a SQLite search cache.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Optional

from agent.memory_provider import MemoryProvider, RecallStatus, spawn_context_thread

from .config import DEFAULTS, NAME, data_dir, load_config
from .dream import Dreamer, hermes_llm
from .store import INDEX, MemoryPathError, MemoryStore

logger = logging.getLogger(__name__)

_LLM: Any = None  # ctx.llm from register(); the dream pass calls the model through it

GUIDANCE = """\
# Memory (dreaming)
You have a memory folder that persists between sessions. It holds what earlier sessions learned
that this one would otherwise have to rediscover.
- `index.md` (shown below) is loaded into every session: what matters most, and a map of the rest.
- `wiki/` holds consolidated pages, one per subject, maintained offline between sessions.
- `notes/` holds notes written during sessions.
- Transcripts of past sessions are searchable.
Use `mem_search` and `mem_read` when the index points at something relevant or the user refers to
earlier work. Write a note with `mem_write` when the user asks you to remember something, or when
something is clearly worth knowing in a future session. Between sessions an offline pass checks
notes against the transcripts and reorganises them, so a short accurate note is enough."""

TOOLS = [
    {
        "name": "mem_search",
        "description": "Search persistent memory (wiki pages, notes, and transcripts of past sessions) "
                       "for anything related to a query. Returns matching passages with their paths.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Words to look for."},
                "scope": {"type": "string", "enum": ["all", "memory", "transcripts"],
                          "description": "memory = wiki + notes; transcripts = raw past sessions. Default all."},
                "limit": {"type": "integer", "description": "Maximum passages (default 8)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "mem_read",
        "description": "Read a memory file in full (index.md, notes/<name>.md, wiki/<name>.md, or "
                       "transcripts/<session>). With no path, lists every memory file.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File to read; empty to list files."}},
        },
    },
    {
        "name": "mem_write",
        "description": "Write a memory file so future sessions have it: notes/<name>.md for a note, "
                       "wiki/<name>.md for a subject page, index.md for the always-loaded index. "
                       "Replaces the file unless mode is append. Empty content deletes the file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "notes/<name>.md, wiki/<name>.md or index.md"},
                "content": {"type": "string", "description": "Markdown content. Empty string deletes."},
                "mode": {"type": "string", "enum": ["replace", "append"], "description": "Default replace."},
            },
            "required": ["path", "content"],
        },
    },
]


def _tool_digest(messages: Optional[list], max_chars: int = 700, max_items: int = 12) -> list[str]:
    """Compact ``name(args) -> result`` lines for the tool calls of the turn that just ended:
    what the agent actually observed, which is the evidence dreaming later checks notes against."""
    if not messages:
        return []
    start = 0
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], dict) and messages[i].get("role") == "user":
            start = i
            break
    calls: dict[str, str] = {}
    out: list[str] = []
    for msg in messages[start:]:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "assistant":
            for call in msg.get("tool_calls") or []:
                fn = (call or {}).get("function") or {}
                calls[str(call.get("id"))] = f"{fn.get('name', '?')}({str(fn.get('arguments', ''))[:300]})"
        elif msg.get("role") == "tool":
            label = calls.get(str(msg.get("tool_call_id")), msg.get("name") or "tool")
            if label.startswith(("mem_search(", "mem_read(")):
                continue  # recalled memory is not new evidence
            content = msg.get("content")
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)
            out.append(f"{label} -> {text[:max_chars]}")
    return out[:max_items]


class DreamingProvider(MemoryProvider):
    def __init__(self) -> None:
        self._store: Optional[MemoryStore] = None
        self._config: dict[str, Any] = dict(DEFAULTS)
        self._hermes_home = ""
        self._session_id = ""
        self._primary = True
        self._recalled = 0
        self._dream_thread: Optional[threading.Thread] = None

    @property
    def name(self) -> str:
        return NAME

    # ------------------------------------------------------------- lifecycle

    def is_available(self) -> bool:
        return True  # local files only: no credentials, no network

    def initialize(self, session_id: str, **kwargs) -> None:
        self._hermes_home = str(kwargs.get("hermes_home") or "")
        self._session_id = session_id or ""
        self._primary = (kwargs.get("agent_context") or "primary") == "primary"
        self._config = load_config(self._hermes_home)
        self._store = MemoryStore(data_dir(self._hermes_home))
        if self._primary and self._config["auto_dream"]:
            self._maybe_dream_in_background()

    def _dreamer(self) -> Dreamer:
        assert self._store is not None
        return Dreamer(self._store, lambda messages: hermes_llm(messages, _LLM),
                       index_max_lines=int(self._config["index_max_lines"]))

    def _maybe_dream_in_background(self) -> None:
        """Sleep-time compute: while this session starts, consolidate the ones that ended before it."""
        try:
            dreamer = self._dreamer()
            pending = dreamer.pending(exclude_session=self._session_id)
            if len(pending) < int(self._config["dream_min_sessions"]) and not dreamer.unverified():
                return
        except Exception:
            logger.debug("dreaming: could not check pending work", exc_info=True)
            return

        def _run() -> None:
            try:
                report = dreamer.run(exclude_session=self._session_id)
                logger.info("dreaming: %s", report.summary())
            except Exception:
                logger.warning("dreaming: background dream failed", exc_info=True)

        self._dream_thread = spawn_context_thread(_run, name="dreaming-dream")
        self._dream_thread.start()

    def on_session_switch(self, new_session_id: str, **kwargs) -> None:
        self._session_id = new_session_id or self._session_id

    def shutdown(self) -> None:
        thread = self._dream_thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)  # never hold the process open for a dream; the next one resumes it

    # ---------------------------------------------------------------- prompt

    def system_prompt_block(self) -> str:
        if not self._store:
            return ""
        index = self._store.index_text()
        parts = [GUIDANCE, "## index.md", index or "(empty: nothing has been promoted to the index yet)"]
        if not index:
            tree = self._store.tree_text(40)
            if tree:
                parts += ["## Memory files", tree]
        return "\n\n".join(parts)

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        self._recalled = 0
        if not self._store or not query.strip():
            return ""
        self._store.sync()
        budget = int(self._config["prefetch_chars"])
        lines: list[str] = []
        used = 0
        seen_paths: dict[str, int] = {}
        for hit in self._store.search(query, kinds=("wiki", "notes"), limit=8):
            if seen_paths.get(hit.path, 0) >= 2:
                continue
            body = hit.text.strip()[:900]
            entry = f"### {hit.path} — {hit.heading}\n{body}"
            if used + len(entry) > budget * 0.75:
                break
            seen_paths[hit.path] = seen_paths.get(hit.path, 0) + 1
            lines.append(entry)
            used += len(entry)
            self._recalled += 1
        if self._config["recall_transcripts"]:
            current = MemoryStore._session_path(self._store, session_id or self._session_id).stem
            dreamed = self._dreamed_turns()
            excerpts = []
            for hit in self._store.search(query, kinds=("transcripts",), limit=12):
                stem = Path(hit.path).stem
                if stem == current:
                    continue  # this session is already in context
                if hit.ord <= dreamed.get(stem, 0):
                    continue  # already consolidated: the wiki speaks for it (still reachable with mem_search)
                body = " ".join(hit.text.split())[:450]
                if used + len(body) > budget:
                    break
                excerpts.append((hit.ts, f"- {body}"))
                used += len(body)
                self._recalled += 1
                if len(excerpts) >= 3:
                    break
            if excerpts:
                lines.append("### Past session excerpts (raw, not yet consolidated; what the USER said is evidence, "
                             "an ASSISTANT answer from memory is not; where they disagree, the later one is current)\n"
                             + "\n".join(text for _ts, text in sorted(excerpts)))
        if not lines:
            return ""
        return "## Recalled from memory for this message\n\n" + "\n\n".join(lines)

    def _dreamed_turns(self) -> dict:
        """session → number of turns the dream pass has already folded into the wiki."""
        try:
            state = json.loads((self._store.root / "dream" / "state.json").read_text(encoding="utf-8"))
            return {str(k): int(v) for k, v in (state.get("dreamed") or {}).items()}
        except (OSError, ValueError, AttributeError):
            return {}

    def recall_status(self) -> Optional[RecallStatus]:
        return RecallStatus(provider_label="Dreaming", count=self._recalled) if self._recalled else None

    # ----------------------------------------------------------------- write

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "",
                  messages: Optional[list[dict[str, Any]]] = None) -> None:
        if not self._store or not self._primary:
            return
        try:
            self._store.append_turn(session_id or self._session_id, user_content or "",
                                    assistant_content or "", _tool_digest(messages))
        except Exception:
            logger.warning("dreaming: could not record turn", exc_info=True)

    def on_memory_write(self, action: str, target: str, content: str,
                        metadata: Optional[dict[str, Any]] = None) -> None:
        """Mirror built-in memory-tool writes as a note, so dreaming can fold them into the wiki."""
        if not self._store or not self._primary or action not in ("add", "replace") or not (content or "").strip():
            return
        try:
            self._store.write("notes/from-builtin-memory.md", f"- ({target}) {content.strip()}", append=True)
        except Exception:
            logger.debug("dreaming: could not mirror built-in memory write", exc_info=True)

    # ----------------------------------------------------------------- tools

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return TOOLS

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs) -> str:
        if not self._store:
            return json.dumps({"error": "dreaming memory is not initialized"})
        try:
            if tool_name == "mem_search":
                return self._tool_search(args)
            if tool_name == "mem_read":
                return self._tool_read(args)
            if tool_name == "mem_write":
                return self._tool_write(args)
        except MemoryPathError as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps({"error": f"unknown tool {tool_name}"})

    def _tool_search(self, args: dict[str, Any]) -> str:
        scope = args.get("scope") or "all"
        kinds = {"memory": ("index", "wiki", "notes"), "transcripts": ("transcripts",)}.get(
            scope, ("index", "wiki", "notes", "transcripts"))
        limit = max(1, min(int(args.get("limit") or 8), 20))
        self._store.sync()
        hits = self._store.search(str(args.get("query") or ""), kinds=kinds, limit=limit)
        return json.dumps({"results": [
            {"path": h.path, "kind": h.kind, "heading": h.heading, "text": h.text[:1200],
             **({"when": h.ts, "turn": h.ord} if h.kind == "transcripts" else {})} for h in hits
        ]}, ensure_ascii=False)

    def _tool_read(self, args: dict[str, Any]) -> str:
        path = str(args.get("path") or "").strip().lstrip("/")
        if not path or path in (".", "/"):
            return json.dumps({"index": self._store.index_text(), "files": self._store.tree_text(200),
                               "sessions": list(self._store.sessions())[-30:]}, ensure_ascii=False)
        if path.startswith("transcripts/"):
            session = Path(path).name.removesuffix(".jsonl")
            rows = self._store.read_session(session)
            if not rows:
                return json.dumps({"error": f"no transcript for session {session!r}"})
            text = "\n\n".join(self._store.format_turn(r, max_chars=3000) for r in rows)
            return json.dumps({"path": path, "content": text[:16000]}, ensure_ascii=False)
        content = self._store.read(path)
        if content is None:
            return json.dumps({"error": f"{path} does not exist", "files": self._store.tree_text(60)})
        return json.dumps({"path": self._store.normalize(path), "content": content}, ensure_ascii=False)

    def _tool_write(self, args: dict[str, Any]) -> str:
        if not self._primary:
            return json.dumps({"error": "memory is read-only in subagent and cron contexts"})
        path, content = str(args.get("path") or ""), str(args.get("content") or "")
        if not content.strip():
            return json.dumps({"deleted": self._store.delete(path), "path": self._store.normalize(path)})
        rel = self._store.write(path, content, append=(args.get("mode") == "append"))
        result: dict[str, Any] = {"saved": rel, "chars": len(self._store.read(rel) or "")}
        if rel == INDEX and (self._store.read(rel) or "").count("\n") > 200:
            result["warning"] = "index.md is over 200 lines; only the first 200 are loaded into sessions"
        return json.dumps(result)

    # ---------------------------------------------------------------- config

    def get_config_schema(self) -> list[dict[str, Any]]:
        return [{
            "key": "auto_dream", "type": "boolean", "default": True,
            "description": "Consolidate finished sessions in the background when a new session starts "
                           "(uses your configured model). Off = only `hermes dreaming dream`.",
        }]

    def save_config(self, values: dict[str, Any], hermes_home: str) -> None:
        path = data_dir(hermes_home) / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        config = load_config(hermes_home)
        for key, value in (values or {}).items():
            if key in DEFAULTS:
                if isinstance(DEFAULTS[key], bool) and isinstance(value, str):
                    value = value.strip().lower() in ("1", "true", "yes", "y", "on")
                config[key] = value
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def register(ctx) -> None:
    global _LLM
    _LLM = getattr(ctx, "llm", None)
    ctx.register_memory_provider(DreamingProvider())
