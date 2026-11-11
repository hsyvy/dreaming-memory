#!/usr/bin/env bash
# Unit tests (no model calls). Uses Hermes' own interpreter so the real MemoryManager is exercised.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
hermes_src="${HERMES_SRC:-$HOME/.hermes/hermes-agent}"
home="$(mktemp -d)"
trap 'rm -rf "$home"' EXIT
cd "$here"
HERMES_HOME="$home" PYTHONPATH="$hermes_src:$here" "$hermes_src/venv/bin/python" -m unittest discover -s tests -v "$@"
