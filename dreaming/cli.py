"""``hermes dreaming <status|dream|search|show>`` — available while dreaming is the active memory provider."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _load():
    """Import the provider package without assuming how Hermes named it on sys.path."""
    if __package__:
        from .config import DEFAULTS, data_dir, load_config
        from .dream import Dreamer, hermes_llm
        from .store import MemoryStore
    else:  # executed as a loose file
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from dreaming.config import DEFAULTS, data_dir, load_config
        from dreaming.dream import Dreamer, hermes_llm
        from dreaming.store import MemoryStore
    return DEFAULTS, data_dir, load_config, Dreamer, hermes_llm, MemoryStore


def _open():
    from hermes_constants import get_hermes_home

    _defaults, data_dir, load_config, Dreamer, hermes_llm, MemoryStore = _load()
    home = get_hermes_home()
    config = load_config(home)
    store = MemoryStore(data_dir(home))
    dreamer = Dreamer(store, hermes_llm, index_max_lines=int(config["index_max_lines"]), say=print)
    return store, dreamer, config


def dreaming_command(args) -> None:
    sub = getattr(args, "dreaming_command", None)
    store, dreamer, config = _open()

    if sub == "dream":
        report = dreamer.run(force=bool(getattr(args, "force", False)))
        if getattr(args, "json", False):
            print(json.dumps({"summary": report.summary(), "sessions": report.sessions,
                              "written": sorted(set(report.written)), "deleted": sorted(set(report.deleted)),
                              "log": report.log, "llm_calls": report.llm_calls, "seconds": report.seconds,
                              "skipped": report.skipped}, indent=2))
            return
        print(report.summary())
        for line in report.log:
            print(f"  - {line}")
        return

    if sub == "search":
        for hit in store.search(" ".join(args.query), limit=args.limit):
            where = f"{hit.path} (turn {hit.ord}, {hit.ts})" if hit.kind == "transcripts" else f"{hit.path} — {hit.heading}"
            print(f"\n## {where}\n{hit.text[:600]}")
        return

    if sub == "show":
        path = getattr(args, "path", "") or "index.md"
        content = store.read(path)
        print(content if content is not None else f"{path} does not exist")
        return

    # status (default)
    state = dreamer.load_state()
    sessions = store.sessions()
    pending = dreamer.pending()
    files = store.files()
    memory, transcripts = store.memory_chars(), store.transcript_chars()
    print(f"store:        {store.root}")
    print(f"sessions:     {len(sessions)} recorded, {len(pending)} with un-dreamed turns")
    print(f"memory files: {len(files)} ({memory:,} chars); transcripts {transcripts:,} chars")
    if transcripts and memory > transcripts:
        print("              warning: memory is larger than its sources — it is abstracting nothing")
    print(f"index.md:     {len((store.read('index.md') or '').splitlines())} lines "
          f"(dream keeps it under {config['index_max_lines']})")
    print(f"unverified:   {len(dreamer.unverified(state))} file(s) changed since last dream")
    print(f"broken links: {len(store.broken_links())}")
    print(f"dream runs:   {state.get('runs', 0)}; last {state.get('last_run', 'never')}")
    print(f"auto_dream:   {config['auto_dream']}")


def register_cli(subparser) -> None:
    subs = subparser.add_subparsers(dest="dreaming_command")
    subs.add_parser("status", help="Show memory size, pending sessions and last dream")
    dream = subs.add_parser("dream", help="Run a dream pass now (verify, build wiki, repair links, rewrite index)")
    dream.add_argument("--force", action="store_true", help="Run even if nothing changed since the last dream")
    dream.add_argument("--json", action="store_true", help="Print the report as JSON")
    search = subs.add_parser("search", help="Search memory and transcripts")
    search.add_argument("query", nargs="+")
    search.add_argument("--limit", type=int, default=6)
    show = subs.add_parser("show", help="Print a memory file (default index.md)")
    show.add_argument("path", nargs="?", default="index.md")
    subparser.set_defaults(func=dreaming_command)
