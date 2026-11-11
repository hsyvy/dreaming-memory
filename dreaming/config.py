"""Provider settings: ``<hermes_home>/dreaming/config.json`` over these defaults.

Kept in its own module so ``cli.py`` can import it without executing the provider package.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

NAME = "dreaming"

DEFAULTS: dict[str, Any] = {
    "auto_dream": True,          # dream in the background at session start when work is pending
    "dream_min_sessions": 1,     # …once at least this many finished sessions are un-dreamed
    "index_max_lines": 60,       # size the dream pass keeps index.md under
    "prefetch_chars": 3000,      # per-message recall budget
    "recall_transcripts": True,  # include raw past-session excerpts in recall
}


def data_dir(hermes_home: str | Path) -> Path:
    return Path(hermes_home) / NAME


def load_config(hermes_home: str | Path) -> dict[str, Any]:
    config = dict(DEFAULTS)
    try:
        stored = json.loads((data_dir(hermes_home) / "config.json").read_text(encoding="utf-8"))
        if isinstance(stored, dict):
            config.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return config
