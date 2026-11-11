"""The dream pass: offline memory maintenance between sessions.

Follows the division of labour in Anthropic's "The components of agent memory":
sessions capture transcripts and quick notes; dreaming looks backward over them and

1. **verifies** notes against the transcripts (the ground truth) and corrects them,
2. **integrates** new sessions into a linked wiki (one page per subject),
3. **repairs** gaps a single session leaves behind (broken links, duplicates),
4. **promotes** what every session needs into a small ``index.md`` and pushes detail down.

The model only ever returns file operations in a plain delimiter format, which this
module validates and applies. ``llm`` is any ``callable(messages) -> str`` so the pass
is testable without a model.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .store import INDEX, WRITABLE_DIRS, MemoryPathError, MemoryStore

LLM = Callable[[list], str]

DEFAULT_INSTRUCTIONS = """\
This memory serves a general-purpose assistant that works with one person over many sessions.
Organise it around that person and their ongoing work: who they are and how they like to work,
the projects, systems and people involved, decisions and their reasons, procedures that were
worked out the hard way, and the current state of anything in progress.
"""

SYSTEM = """\
You are the offline memory-maintenance ("dreaming") process of an AI agent. The agent is not
running. You review its memory folder against the raw session transcripts and return file
operations that make the memory more correct and easier to use in future sessions.

Memory layout
- index.md  — loaded into EVERY future session. Must stay small.
- notes/*.md — quick notes the agent wrote during sessions. May be wrong or out of date.
- wiki/*.md — consolidated pages you maintain: one page per subject, linked with [[page-name]].
- transcripts — what was actually said and observed. Read-only ground truth.

Rules
- Transcripts are the ground truth. A memory claim that a transcript contradicts is wrong: fix it.
- When transcripts disagree with each other, the LATER statement wins (compare timestamps),
  unless the later one is only a question or a hypothetical. State the current value; mention
  the former one only when knowing it prevents a mistake ("was X until 2026-11-03").
- In a transcript, evidence is what the USER said and what TOOL lines show. An ASSISTANT line
  that only answers from memory is not evidence: it may be repeating a stale note. It never
  overrides a USER statement, however recent it is.
- A session often changes a fact without naming it: by a pronoun, another name for the same
  thing, or a reference to an earlier conversation. Resolve such references from the other
  sessions and their order, then update every page the change touches.
- Never add a fact that is in neither the transcripts nor existing memory. Do not guess.
- Copy exact values verbatim: names, numbers, dates, IDs, paths, commands, quoted wording.
- Abstract, don't transcribe. A page that is as long as its sources abstracts nothing.
- One subject per wiki page (a person, project, system, procedure, preference area). Merge
  duplicates. Prefer updating an existing page over creating a near-copy.
- Link related pages with [[page-name]] (the wiki file name without .md). Only link to pages
  that exist or that you create in this same response.
- Skip things with no future value: greetings, one-off chatter, anything re-derivable instantly.

Output format — return ONLY operations, no commentary:

<<<FILE wiki/example-page.md>>>
# Example Page
full new content of the file (always the whole file, never a diff)
<<<END>>>
<<<DELETE notes/obsolete.md>>>
<<<LOG one line saying what you changed and why (e.g. which transcript corrected which claim)>>>

Paths must be index.md, notes/<name>.md or wiki/<name>.md. If nothing needs to change, return
exactly: <<<LOG no changes>>>
"""

_FILE_RE = re.compile(r"<<<FILE\s+([^>\n]+?)\s*>>>[ \t]*\n(.*?)\n?<<<END>>>", re.DOTALL)
_DELETE_RE = re.compile(r"<<<DELETE\s+([^>\n]+?)\s*>>>")
_LOG_RE = re.compile(r"<<<LOG\s+(.+?)\s*>>>", re.DOTALL)

MAX_PAGE_CHARS = 12_000
BATCH_CHARS = 28_000
CONTEXT_CHARS = 24_000


@dataclass
class DreamReport:
    sessions: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    llm_calls: int = 0
    skipped: str = ""
    seconds: float = 0.0

    def summary(self) -> str:
        if self.skipped:
            return f"dream skipped: {self.skipped}"
        return (f"dreamed {len(self.sessions)} session(s) in {self.seconds:.0f}s with {self.llm_calls} model call(s): "
                f"{len(set(self.written))} file(s) written, {len(set(self.deleted))} deleted")


def parse_ops(text: str) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    """``(files, deletes, logs)`` from a model response in the delimiter format."""
    files = [(m.group(1).strip(), m.group(2)) for m in _FILE_RE.finditer(text or "")]
    rest = _FILE_RE.sub("", text or "")
    deletes = [m.group(1).strip() for m in _DELETE_RE.finditer(rest)]
    logs = [" ".join(m.group(1).split()) for m in _LOG_RE.finditer(rest)]
    return files, deletes, logs


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class Dreamer:
    def __init__(self, store: MemoryStore, llm: LLM, *, index_max_lines: int = 60,
                 say: Optional[Callable[[str], None]] = None):
        self.store = store
        self.llm = llm
        self.index_max_lines = index_max_lines
        self.say = say or (lambda _msg: None)
        self.dir = store.root / "dream"
        self.state_path = self.dir / "state.json"
        self.log_path = self.dir / "log.md"
        self.instructions_path = self.dir / "instructions.md"
        self.lock_path = self.dir / "dream.lock"

    # ------------------------------------------------------------------ state

    def load_state(self) -> dict:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            state = {}
        state.setdefault("dreamed", {})    # session → turns already integrated
        state.setdefault("verified", {})   # path → digest of the content last checked
        state.setdefault("runs", 0)
        return state

    def _save_state(self, state: dict) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def instructions(self) -> str:
        if not self.instructions_path.exists():
            self.instructions_path.write_text(DEFAULT_INSTRUCTIONS, encoding="utf-8")
        return self.instructions_path.read_text(encoding="utf-8").strip()

    def pending(self, *, exclude_session: str = "") -> dict[str, tuple[int, int]]:
        """session → (turns already dreamed, turns recorded) for sessions with new turns."""
        dreamed = self.load_state()["dreamed"]
        skip = MemoryStore._session_path(self.store, exclude_session).stem if exclude_session else ""
        return {sid: (int(dreamed.get(sid, 0)), n) for sid, n in self.store.sessions().items()
                if n > int(dreamed.get(sid, 0)) and sid != skip}

    def unverified(self, state: Optional[dict] = None) -> list[str]:
        """Notes and wiki pages whose content changed since dreaming last checked them."""
        verified = (state or self.load_state())["verified"]
        return [rel for rel in self.store.files(kinds=WRITABLE_DIRS)
                if verified.get(rel) != _digest(self.store.read(rel) or "")]

    # ------------------------------------------------------------------- lock

    def _acquire(self) -> bool:
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if not self._lock_is_stale():
                return False
            self.lock_path.unlink(missing_ok=True)
            return self._acquire()
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True

    def _lock_is_stale(self) -> bool:
        """A lock is stale after an hour, or as soon as the process that took it is gone
        (a one-shot `hermes -z` run can exit in the middle of a background pass)."""
        try:
            if time.time() - self.lock_path.stat().st_mtime > 3600:
                return True
            pid = int(self.lock_path.read_text(encoding="utf-8").strip() or 0)
        except (FileNotFoundError, ValueError):
            return True
        if pid <= 0:
            return True
        if os.name != "posix":  # os.kill(pid, 0) would terminate the process on Windows
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return False

    # ---------------------------------------------------------------- helpers

    def _call(self, report: DreamReport, phase: str, user: str) -> str:
        report.llm_calls += 1
        self.say(f"  {phase}: asking the model ({len(user):,} chars of context)")
        goal = self.instructions()
        system = SYSTEM + ("\nWhat this memory is for (use it to judge what matters):\n" + goal if goal else "")
        return self.llm([{"role": "system", "content": system}, {"role": "user", "content": user}]) or ""

    def _apply(self, report: DreamReport, phase: str, response: str, state: dict) -> list[str]:
        files, deletes, logs = parse_ops(response)
        touched: list[str] = []
        for raw_path, content in files:
            try:
                rel = self.store.normalize(raw_path)
            except MemoryPathError as exc:
                report.log.append(f"{phase}: rejected write: {exc}")
                continue
            if not content.strip():
                continue
            if len(content) > MAX_PAGE_CHARS:
                report.log.append(f"{phase}: rejected {rel}: {len(content):,} chars is a transcript, not a page")
                continue
            if rel == INDEX:
                content = self._cap_index(content, report)
            if (self.store.read(rel) or "").strip() == content.strip():
                state["verified"][rel] = _digest(self.store.read(rel) or "")
                continue
            self.store.write(rel, content)
            state["verified"][rel] = _digest(self.store.read(rel) or "")
            report.written.append(rel)
            touched.append(rel)
        for raw_path in deletes:
            try:
                rel = self.store.normalize(raw_path)
            except MemoryPathError as exc:
                report.log.append(f"{phase}: rejected delete: {exc}")
                continue
            if rel != INDEX and self.store.delete(rel):
                state["verified"].pop(rel, None)
                report.deleted.append(rel)
        for line in logs:
            if line.lower() != "no changes":
                report.log.append(f"{phase}: {line}")
        return touched

    def _cap_index(self, content: str, report: DreamReport) -> str:
        lines = content.rstrip("\n").splitlines()
        if len(lines) > self.index_max_lines:
            report.log.append(f"index: model wrote {len(lines)} lines; kept the first {self.index_max_lines}")
            lines = lines[: self.index_max_lines]
        return "\n".join(lines)

    def _memory_block(self, paths: list[str], budget: int = CONTEXT_CHARS) -> str:
        """Full text of *paths* until the budget runs out, then titles only."""
        out, used, listed = [], 0, []
        for rel in paths:
            text = self.store.read(rel)
            if text is None:
                continue
            if used + len(text) <= budget:
                out.append(f"--- {rel} ---\n{text.strip()}")
                used += len(text)
            else:
                listed.append(f"- {rel} — {self.store.describe(rel)['title']}")
        block = "\n\n".join(out) or "(none)"
        if listed:
            block += "\n\nOther memory files (not shown; do not rewrite these blind):\n" + "\n".join(listed)
        return block

    def _relevant_files(self, text: str, limit: int = 12) -> list[str]:
        """Memory files most related to *text*; everything when the memory is still small."""
        all_files = self.store.files(kinds=WRITABLE_DIRS)
        if sum(self.store.describe(rel)["chars"] for rel in all_files) <= CONTEXT_CHARS:
            return all_files
        ranked: list[str] = []
        for hit in self.store.search(text, kinds=WRITABLE_DIRS, limit=limit * 3):
            if hit.path not in ranked:
                ranked.append(hit.path)
        return ranked[:limit]

    def _evidence(self, text: str, limit: int = 6, max_chars: int = 1400) -> list[tuple[str, int, str]]:
        """``(session, turn, formatted turn)`` transcript turns most related to *text*, oldest first."""
        rows = []
        for hit in self.store.search(text, kinds=("transcripts",), limit=limit):
            rows.append((hit.ts, hit.session_id, hit.ord, hit.text[:max_chars]))
        rows.sort()
        return [(sid, turn, body) for _ts, sid, turn, body in rows]

    # ----------------------------------------------------------------- phases

    def _verify(self, report: DreamReport, state: dict) -> None:
        """Check notes/wiki pages changed since the last dream against transcript evidence."""
        todo = self.unverified(state)
        batch: list[str] = []
        size = 0
        for rel in todo + [None]:
            text = self.store.read(rel) if rel else None
            if rel is None or (batch and size + len(text or "") > BATCH_CHARS // 2):
                if batch:
                    self._verify_batch(report, state, batch)
                batch, size = [], 0
            if rel and text is not None:
                batch.append(rel)
                size += len(text)

    def _verify_batch(self, report: DreamReport, state: dict, batch: list[str]) -> None:
        seen: dict[tuple[str, int], str] = {}
        for rel in batch:
            for sid, turn, body in self._evidence(self.store.read(rel) or ""):
                seen.setdefault((sid, turn), body)
        for rel in batch:   # checked now, whatever the outcome; rewritten files are re-stamped in _apply
            state["verified"][rel] = _digest(self.store.read(rel) or "")
        if not seen:
            return  # nothing in the transcripts speaks to these files: no ground truth to check against
        evidence = "\n\n".join(seen.values())
        user = (
            "TASK: verify memory against the transcripts.\n"
            "Check every factual claim in the memory files below against the transcript excerpts. "
            "Rewrite a file ONLY if a claim in it is contradicted or superseded by the transcripts; "
            "change the wrong claims and keep the rest of the file as it is. Log each correction with "
            "the session that proves it. Do not create new files in this step.\n\n"
            f"MEMORY FILES TO VERIFY\n{self._memory_block(batch, budget=BATCH_CHARS)}\n\n"
            f"TRANSCRIPT EXCERPTS (ground truth, oldest first)\n{evidence}"
        )
        self._apply(report, "verify", self._call(report, "verify", user), state)

    def _integrate(self, report: DreamReport, state: dict, pending: dict[str, tuple[int, int]]) -> None:
        """Fold new transcript turns into the wiki, correcting anything they supersede."""
        batch: list[str] = []
        covered: dict[str, int] = {}
        size = 0

        def flush() -> None:
            nonlocal batch, covered, size
            if not batch:
                return
            new_text = "\n\n".join(batch)
            user = (
                "TASK: integrate new sessions into memory.\n"
                "Read the new transcript turns. Update or create wiki pages so that a future session "
                "can find what these sessions established without rereading them. Where the new turns "
                "contradict or supersede existing memory, correct the existing file. Fold useful agent "
                "notes (notes/*.md) into the wiki and delete a note once a wiki page fully covers it. "
                "Do not rewrite index.md in this step.\n\n"
                f"CURRENT INDEX\n{self.store.index_text() or '(empty)'}\n\n"
                f"EXISTING MEMORY FILES (most related to the new turns)\n"
                f"{self._memory_block(self._relevant_files(new_text))}\n\n"
                f"NEW TRANSCRIPT TURNS (ground truth, oldest first)\n{new_text}"
            )
            self._apply(report, "integrate", self._call(report, "integrate", user), state)
            state["dreamed"].update(covered)
            self._save_state(state)
            batch, covered, size = [], {}, 0

        for sid, (done, total) in pending.items():
            for row in self.store.read_session(sid)[done:total]:
                text = self.store.format_turn(row, max_chars=6000)
                if batch and size + len(text) > BATCH_CHARS:
                    flush()
                batch.append(text)
                size += len(text)
                covered[sid] = int(row.get("turn") or covered.get(sid, done) + 1)
            covered[sid] = total
            report.sessions.append(sid)
        flush()

    def _repair_links(self, report: DreamReport, state: dict) -> None:
        broken = self.store.broken_links()
        if not broken:
            return
        files = list(dict.fromkeys(rel for rel, _ in broken))
        targets = list(dict.fromkeys(target for _, target in broken))
        evidence = []
        for target in targets[:8]:
            turns = self._evidence(target, limit=3, max_chars=900)
            if turns:
                evidence.append(f"About [[{target}]]:\n" + "\n\n".join(body for _s, _t, body in turns))
        user = (
            "TASK: repair links.\n"
            "The files below contain [[links]] to pages that do not exist. For each missing target: "
            "repoint the link to an existing page about the same subject, OR create the page if the "
            "transcript excerpts give you real content for it, OR remove the link markup (keep the "
            "words). Do not invent content.\n\n"
            f"MISSING TARGETS\n" + "\n".join(f"- [[{t}]] (linked from {rel})" for rel, t in broken) + "\n\n"
            f"EXISTING PAGES\n{self.store.tree_text(200) or '(none)'}\n\n"
            f"FILES WITH BROKEN LINKS\n{self._memory_block(files)}\n\n"
            f"TRANSCRIPT EXCERPTS\n" + ("\n\n".join(evidence) or "(none found)")
        )
        self._apply(report, "links", self._call(report, "links", user), state)

    def _promote(self, report: DreamReport, state: dict) -> None:
        """Rewrite index.md: the small layer that every session starts with."""
        pages = self.store.files(kinds=WRITABLE_DIRS)
        user = (
            "TASK: rewrite index.md, the top of the memory hierarchy.\n"
            f"index.md is injected into every future session, so it must stay under {self.index_max_lines} "
            "lines and every line must earn its place. Write it in two parts:\n"
            "1. What nearly every session needs: who the user is and standing preferences, current "
            "goals and state of work in progress, and the few facts that are needed most often or "
            "that prevent a known mistake. State current values only.\n"
            "2. A map: one line per wiki page, `- [[page-name]] — what you will find there`, so a "
            "session knows what it knows and where to look.\n"
            "Move detail DOWN: if something needs more than a line, it belongs in a wiki page with a "
            "link from here. Return a single <<<FILE index.md>>> operation.\n\n"
            f"CURRENT INDEX\n{self.store.read(INDEX) or '(empty)'}\n\n"
            f"MEMORY FILES\n{self._memory_block(pages, budget=CONTEXT_CHARS * 2)}"
        )
        response = self._call(report, "index", user)
        files, _deletes, logs = parse_ops(response)
        only_index = "".join(f"<<<FILE {p}>>>\n{c}\n<<<END>>>\n" for p, c in files if p.strip().lstrip("./") in ("index.md", "index"))
        self._apply(report, "index", only_index + "".join(f"<<<LOG {line}>>>\n" for line in logs), state)

    # -------------------------------------------------------------------- run

    def _backup(self) -> None:
        """Snapshot memory before changing it; a bad dream must be undoable. Keeps the last 5."""
        base = self.dir / "backups"
        dest = base / time.strftime("%Y%m%d-%H%M%S")
        dest.mkdir(parents=True, exist_ok=True)
        for sub in WRITABLE_DIRS:
            if (self.store.root / sub).exists():
                shutil.copytree(self.store.root / sub, dest / sub, dirs_exist_ok=True)
        if (self.store.root / INDEX).exists():
            shutil.copy2(self.store.root / INDEX, dest / INDEX)
        for old in sorted(p for p in base.iterdir() if p.is_dir())[:-5]:
            shutil.rmtree(old, ignore_errors=True)

    def run(self, *, force: bool = False, exclude_session: str = "") -> DreamReport:
        """One dream pass. Without *force* it is skipped when nothing changed since the last one."""
        report = DreamReport()
        started = time.time()
        self.store.sync()
        state = self.load_state()
        pending = self.pending(exclude_session=exclude_session)
        if not force and not pending and not self.unverified(state):
            report.skipped = "no new sessions and no changed notes"
            return report
        if not self._acquire():
            report.skipped = "another dream is running"
            return report
        try:
            self._backup()
            self.say(f"dreaming over {len(pending)} session(s) with new turns")
            self._verify(report, state)
            self._integrate(report, state, pending)
            self._repair_links(report, state)
            if report.written or report.deleted or force or not self.store.read(INDEX):
                self._promote(report, state)
            state["runs"] = int(state.get("runs", 0)) + 1
            state["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            self._save_state(state)
        finally:
            self.lock_path.unlink(missing_ok=True)
        report.seconds = time.time() - started
        self._append_log(report)
        return report

    def _append_log(self, report: DreamReport) -> None:
        lines = [f"## {time.strftime('%Y-%m-%d %H:%M:%S')} — {report.summary()}"]
        lines += [f"- wrote {rel}" for rel in dict.fromkeys(report.written)]
        lines += [f"- deleted {rel}" for rel in dict.fromkeys(report.deleted)]
        lines += [f"- {line}" for line in report.log]
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n\n")


def hermes_llm(messages: list, llm: Any = None) -> str:
    """Dream with the model Hermes is configured to use, through Hermes' plugin LLM API
    (``ctx.llm``: host-owned credentials, no keys in the plugin).

    In a session the provider passes the ``ctx.llm`` it was registered with. ``hermes dreaming``
    commands load only ``cli.py``, without a plugin context, so they build the same facade for
    this plugin's own id.
    """
    if llm is None:
        from agent.plugin_llm import PluginLlm

        llm = PluginLlm(plugin_id="dreaming")
    result = llm.complete(messages=messages, timeout=600, purpose="dreaming.dream")
    return result.text or ""
