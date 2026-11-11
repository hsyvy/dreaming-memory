"""On-disk memory store for the dreaming provider.

Layout under ``<hermes_home>/dreaming/``::

    index.md                    top of the hierarchy; loaded into every session (capped)
    notes/*.md                  written by the agent during sessions
    wiki/*.md                   consolidated pages maintained by the dream pass, [[linked]]
    transcripts/<session>.jsonl raw turns: the ground truth dreaming checks memory against
    dream/                      dream state, log, backups, goal instructions
    search.db                   SQLite FTS5 index; a cache, rebuilt from the files above

Everything except ``search.db`` is plain text a person can read and edit.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

INDEX = "index.md"
WRITABLE_DIRS = ("notes", "wiki")
LINK_RE = re.compile(r"\[\[([^\]\|#\n]+)(?:[#\|][^\]\n]*)?\]\]")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}")
_SAFE_SESSION_RE = re.compile(r"[^A-Za-z0-9_.-]")
_STOPWORDS = frozenset("""
a about above after again all also am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has
have having he her here hers him his how if in into is it its just let me more most my no nor not
now of off on once only or other our out over own please same she should so some such than that
the their them then there these they this those through to too under until up us very was we were
what when where which while who whom why will with would you your tell know remember need want
""".split())

CHUNK_CHARS = 1500


class MemoryPathError(ValueError):
    """A memory path outside the writable area, or not a markdown file."""


@dataclass
class Hit:
    path: str
    kind: str          # "wiki" | "notes" | "index" | "transcripts"
    heading: str
    text: str
    score: float
    ord: int = 0       # chunk number, or turn number for transcripts
    ts: str = ""       # ISO timestamp for transcript turns
    session_id: str = ""


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "untitled"


def query_terms(text: str, limit: int = 24) -> list[str]:
    """Distinct content words of *text*, in order, for an OR full-text query."""
    seen: list[str] = []
    for tok in _TOKEN_RE.findall(text.lower()):
        if tok in _STOPWORDS or tok in seen:
            continue
        seen.append(tok)
        if len(seen) >= limit:
            break
    return seen


def chunk_markdown(text: str) -> list[tuple[str, str]]:
    """Split a page into ``(heading, body)`` chunks along headings, then by paragraph."""
    title, heading, buf = "", "", []
    out: list[tuple[str, str]] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if not body:
            return
        label = title if not heading or heading == title else f"{title} › {heading}" if title else heading
        while len(body) > CHUNK_CHARS:
            cut = body.rfind("\n\n", 0, CHUNK_CHARS)
            cut = cut if cut > CHUNK_CHARS // 3 else CHUNK_CHARS
            out.append((label, body[:cut].strip()))
            body = body[cut:].strip()
        if body:
            out.append((label, body))

    for line in text.splitlines():
        if line.startswith("#"):
            flush()
            buf = []
            heading = line.lstrip("#").strip()
            if not title:
                title = heading
            continue
        buf.append(line)
    flush()
    return out


def page_title(text: str, fallback: str = "") -> str:
    for line in text.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()
        if line.strip():
            break
    return fallback


class MemoryStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self._lock = threading.RLock()
        for sub in (*WRITABLE_DIRS, "transcripts", "dream"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self._db_path = self.root / "search.db"
        self._fts = True
        self._init_db()

    # ------------------------------------------------------------------ paths

    def normalize(self, rel: str) -> str:
        """Canonical relative path of a writable memory file, or raise MemoryPathError."""
        rel = (rel or "").strip().replace("\\", "/").lstrip("/")
        if rel.startswith("./"):
            rel = rel[2:]
        if rel in ("index", INDEX):
            return INDEX
        parts = rel.split("/")
        if len(parts) < 2 or parts[0] not in WRITABLE_DIRS or any(p in ("", ".", "..") for p in parts):
            raise MemoryPathError(
                f"{rel!r} is not a memory path: use index.md, notes/<name>.md or wiki/<name>.md")
        if not parts[-1].endswith(".md"):
            parts[-1] += ".md"
        return "/".join(parts)

    def _abs(self, rel: str) -> Path:
        return self.root / rel

    # ------------------------------------------------------------------ files

    def read(self, rel: str) -> Optional[str]:
        path = self._abs(self.normalize(rel))
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def write(self, rel: str, content: str, *, append: bool = False) -> str:
        rel = self.normalize(rel)
        path = self._abs(rel)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            if append and path.exists():
                content = path.read_text(encoding="utf-8").rstrip("\n") + "\n\n" + content.strip("\n")
            tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            tmp.write_text(content.rstrip("\n") + "\n", encoding="utf-8")
            os.replace(tmp, path)
            self._index_file(rel)
        return rel

    def delete(self, rel: str) -> bool:
        rel = self.normalize(rel)
        with self._lock:
            try:
                self._abs(rel).unlink()
            except FileNotFoundError:
                return False
            self._drop_file(rel)
        return True

    def files(self, kinds: Iterable[str] = ("index", *WRITABLE_DIRS)) -> list[str]:
        """Relative paths of memory files, index first, then sorted."""
        out: list[str] = []
        if "index" in kinds and self._abs(INDEX).exists():
            out.append(INDEX)
        for sub in WRITABLE_DIRS:
            if sub in kinds:
                base = self.root / sub
                out.extend(sorted(str(p.relative_to(self.root)).replace(os.sep, "/")
                                  for p in base.rglob("*.md") if not p.name.startswith(".")))
        return out

    def describe(self, rel: str) -> dict:
        text = self.read(rel) or ""
        return {"path": rel, "title": page_title(text, Path(rel).stem), "chars": len(text),
                "lines": text.count("\n")}

    def tree_text(self, max_lines: int = 60) -> str:
        """One line per memory file: ``path — title (N chars)``."""
        lines = []
        for rel in self.files(kinds=WRITABLE_DIRS):
            d = self.describe(rel)
            lines.append(f"- {rel} — {d['title']} ({d['chars']} chars)")
        if len(lines) > max_lines:
            lines = lines[:max_lines] + [f"- … {len(lines) - max_lines} more (use mem_search)"]
        return "\n".join(lines)

    def index_text(self, max_lines: int = 200, max_bytes: int = 25_000) -> str:
        """The part of index.md that is loaded into every session."""
        text = self.read(INDEX) or ""
        lines = text.splitlines()
        cut = len(lines) > max_lines
        text = "\n".join(lines[:max_lines])
        raw = text.encode("utf-8")
        if len(raw) > max_bytes:
            text, cut = raw[:max_bytes].decode("utf-8", "ignore"), True
        if cut:
            text += "\n[index.md truncated here: the rest is not loaded. Read it with mem_read.]"
        return text.strip()

    def memory_chars(self) -> int:
        return sum(self.describe(rel)["chars"] for rel in self.files())

    # ------------------------------------------------------------------ links

    def link_targets(self) -> dict[str, str]:
        """slug → path for every page a ``[[link]]`` can resolve to."""
        targets: dict[str, str] = {}
        for rel in self.files(kinds=WRITABLE_DIRS):
            stem = rel[:-3]
            targets.setdefault(slugify(Path(stem).name), rel)
            targets[slugify(stem)] = rel
        return targets

    def resolve_link(self, target: str, targets: Optional[dict[str, str]] = None) -> Optional[str]:
        targets = self.link_targets() if targets is None else targets
        target = target.strip()
        if target.endswith(".md"):
            target = target[:-3]
        return targets.get(slugify(target)) or targets.get(slugify(Path(target).name))

    def broken_links(self) -> list[tuple[str, str]]:
        """``(file, target)`` for every ``[[target]]`` that resolves to no page."""
        targets = self.link_targets()
        broken = []
        for rel in self.files():
            for target in dict.fromkeys(LINK_RE.findall(self.read(rel) or "")):
                if not self.resolve_link(target, targets):
                    broken.append((rel, target.strip()))
        return broken

    # ------------------------------------------------------------- transcripts

    def _session_path(self, session_id: str) -> Path:
        safe = _SAFE_SESSION_RE.sub("_", session_id or "unknown")[:120]
        return self.root / "transcripts" / f"{safe}.jsonl"

    def append_turn(self, session_id: str, user: str, assistant: str,
                    tools: Optional[list[str]] = None, ts: Optional[str] = None) -> int:
        """Append one completed turn to the session's transcript; returns its turn number."""
        path = self._session_path(session_id)
        with self._lock:
            turn = 1
            if path.exists():
                with path.open(encoding="utf-8") as fh:
                    turn = sum(1 for _ in fh) + 1
            row = {"ts": ts or time.strftime("%Y-%m-%dT%H:%M:%S"), "session": session_id,
                   "turn": turn, "user": user or "", "assistant": assistant or ""}
            if tools:
                row["tools"] = tools
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            self._index_file(str(path.relative_to(self.root)).replace(os.sep, "/"))
        return turn

    def sessions(self) -> dict[str, int]:
        """session file stem → number of recorded turns, oldest first."""
        out: dict[str, int] = {}
        for path in sorted((self.root / "transcripts").glob("*.jsonl"), key=lambda p: p.stat().st_mtime):
            with path.open(encoding="utf-8") as fh:
                out[path.stem] = sum(1 for line in fh if line.strip())
        return out

    def read_session(self, session: str) -> list[dict]:
        path = self._session_path(session)
        rows = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows

    @staticmethod
    def format_turn(row: dict, *, max_chars: int = 0) -> str:
        parts = [f"[{row.get('ts', '')} session {row.get('session', '')} turn {row.get('turn', '')}]",
                 f"USER: {row.get('user', '')}"]
        for tool in row.get("tools") or []:
            parts.append(f"TOOL: {tool}")
        parts.append(f"ASSISTANT: {row.get('assistant', '')}")
        text = "\n".join(parts)
        if max_chars and len(text) > max_chars:
            text = text[:max_chars] + " …[truncated]"
        return text

    def transcript_chars(self) -> int:
        return sum(p.stat().st_size for p in (self.root / "transcripts").glob("*.jsonl"))

    # ------------------------------------------------------------------ search

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=15)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, sig TEXT)")
                try:
                    conn.execute(
                        "CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5("
                        "text, heading, path UNINDEXED, kind UNINDEXED, ord UNINDEXED, ts UNINDEXED, "
                        "session UNINDEXED, tokenize='porter unicode61')")
                except sqlite3.OperationalError:
                    self._fts = False   # SQLite built without FTS5: fall back to a plain table
                    conn.execute("CREATE TABLE IF NOT EXISTS chunks(text, heading, path, kind, ord, ts, session)")
                conn.commit()
            finally:
                conn.close()
        self.sync()

    @staticmethod
    def _kind(rel: str) -> str:
        return "index" if rel == INDEX else rel.split("/", 1)[0]

    def _sig(self, rel: str) -> str:
        st = self._abs(rel).stat()
        return f"{st.st_mtime_ns}:{st.st_size}"

    def _rows_for(self, rel: str) -> list[tuple]:
        kind = self._kind(rel)
        if kind == "transcripts":
            return [(self.format_turn(row), f"session {row.get('session', '')}", rel, kind,
                     int(row.get("turn") or i + 1), row.get("ts", ""), row.get("session", ""))
                    for i, row in enumerate(self.read_session(Path(rel).stem))]
        text = self._abs(rel).read_text(encoding="utf-8")
        chunks = chunk_markdown(text) or ([(Path(rel).stem, text.strip())] if text.strip() else [])
        return [(body, heading or Path(rel).stem, rel, kind, i, "", "") for i, (heading, body) in enumerate(chunks)]

    def _index_file(self, rel: str, conn: Optional[sqlite3.Connection] = None) -> None:
        own = conn is None
        conn = conn or self._connect()
        try:
            conn.execute("DELETE FROM chunks WHERE path = ?", (rel,))
            conn.executemany("INSERT INTO chunks(text, heading, path, kind, ord, ts, session) VALUES (?,?,?,?,?,?,?)",
                             self._rows_for(rel))
            conn.execute("INSERT OR REPLACE INTO files(path, sig) VALUES (?, ?)", (rel, self._sig(rel)))
            if own:
                conn.commit()
        finally:
            if own:
                conn.close()

    def _drop_file(self, rel: str, conn: Optional[sqlite3.Connection] = None) -> None:
        own = conn is None
        conn = conn or self._connect()
        try:
            conn.execute("DELETE FROM chunks WHERE path = ?", (rel,))
            conn.execute("DELETE FROM files WHERE path = ?", (rel,))
            if own:
                conn.commit()
        finally:
            if own:
                conn.close()

    def sync(self) -> int:
        """Bring the search index in line with the files on disk (edits made by hand, by
        another process, or by copying a store). Returns the number of files reindexed."""
        with self._lock:
            on_disk = self.files() + sorted(
                f"transcripts/{p.name}" for p in (self.root / "transcripts").glob("*.jsonl"))
            conn = self._connect()
            try:
                known = dict(conn.execute("SELECT path, sig FROM files").fetchall())
                changed = 0
                for rel in on_disk:
                    if known.get(rel) != self._sig(rel):
                        self._index_file(rel, conn)
                        changed += 1
                for rel in set(known) - set(on_disk):
                    self._drop_file(rel, conn)
                    changed += 1
                conn.commit()
                return changed
            finally:
                conn.close()

    def search(self, query: str, *, kinds: Iterable[str] = ("index", "wiki", "notes", "transcripts"),
               limit: int = 8) -> list[Hit]:
        """Best-matching chunks for *query* (any content word), best first."""
        terms = query_terms(query)
        kinds = tuple(kinds)
        if not terms or not kinds:
            return []
        marks = ",".join("?" * len(kinds))
        with self._lock:
            conn = self._connect()
            try:
                if self._fts:
                    match = " OR ".join(f'"{t}"' for t in terms)
                    rows = conn.execute(
                        f"SELECT path, kind, heading, text, ord, ts, session, bm25(chunks, 1.0, 2.0) AS rank "
                        f"FROM chunks WHERE chunks MATCH ? AND kind IN ({marks}) ORDER BY rank LIMIT ?",
                        (match, *kinds, limit)).fetchall()
                    return [Hit(path=r[0], kind=r[1], heading=r[2], text=r[3], ord=int(r[4] or 0),
                                ts=r[5] or "", session_id=r[6] or "", score=-float(r[7])) for r in rows]
                rows = conn.execute(
                    f"SELECT path, kind, heading, text, ord, ts, session FROM chunks WHERE kind IN ({marks})",
                    kinds).fetchall()
            finally:
                conn.close()
        scored = []
        for r in rows:
            low = f"{r[2]} {r[3]}".lower()
            score = sum(low.count(t) for t in terms)
            if score:
                scored.append(Hit(path=r[0], kind=r[1], heading=r[2], text=r[3], ord=int(r[4] or 0),
                                  ts=r[5] or "", session_id=r[6] or "", score=float(score)))
        scored.sort(key=lambda h: -h.score)
        return scored[:limit]
