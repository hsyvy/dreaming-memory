# Dreaming — memory for Hermes Agent that consolidates offline

Your agent can search every conversation it has had with you, and still get today's facts wrong.
People rarely announce changes. They say "Halvard has taken over everything of hers", not
"quaywatch is now owned by Halvard". Search finds the session where the old fact was stated, and
the agent repeats it.

Dreaming is a memory provider plugin for [Hermes Agent](https://hermes-agent.nousresearch.com/)
built on the architecture in Anthropic's
[The components of agent memory](https://www.anthropic.com/research/components-of-agent-memory):
**capture in the moment, consolidate offline.** While you work it records every session and lets
the agent write quick notes. Between sessions a **dream pass** rereads the sessions in order,
checks the notes against what was actually said, and rewrites a linked wiki and a short index that
every new session starts with.

Demo video and benchmarks: [github.com/hsyvy/dreaming-memory](https://github.com/hsyvy/dreaming-memory)

| Test (stock Hermes vs. this plugin, after one dream pass) | Stock | Dreaming |
|---|---|---|
| Facts that changed indirectly, correct of 6 (3 runs) | 2, 2, 2 | **6, 6, 6** |
| Facts damaged in the agent's own notes, correct of 4 | 2 | **4** |
| A procedure nobody wrote down, model calls per task | 7.4 | **3.0** |

Small tests on one model; the first was written so that each change shares no keyword with its
question. Method and limits: [RESULTS.md](https://github.com/hsyvy/dreaming-memory/blob/main/RESULTS.md).

## Install

Requires Hermes Agent 0.23.1 or newer. No API keys and no Python dependencies.

```bash
hermes plugins install hsyvy/dreaming-memory/dreaming
```

```bash
hermes config set memory.provider dreaming
```

Start a new session and the agent has it. For a named profile add `-p <profile>` to both commands.

Without the installer, copy the `dreaming/` folder of this repository to `~/.hermes/plugins/dreaming`
(or `~/.hermes/profiles/<name>/plugins/dreaming`) and run the `config set` command above.

To switch back to built-in memory only: `hermes memory off`. Your memory folder stays on disk.

## How it works

| Article component | Here |
|---|---|
| Transcripts as ground truth | Every completed turn is appended to `transcripts/<session>.jsonl`, including what tools returned. |
| Memory notes | The agent writes `notes/*.md` with `mem_write` when something is worth keeping. It is told what memory is for, not what to save. |
| Dreaming corrects memory | The dream pass checks each changed note against transcript evidence and rewrites wrong claims. |
| Dreaming builds representations | New sessions are folded into `wiki/*.md`, one page per subject, linked with `[[page]]`. |
| Dreaming fills gaps | Broken links are repointed, filled from transcripts, or removed; covered notes are deleted. |
| Promotion up the hierarchy | `index.md` is rewritten to stay under 60 lines and is injected into every session. |
| Search plus wiki | Each message recalls the best wiki/note passages first, then raw excerpts from sessions the dream pass has not consolidated yet. |
| Goal-focused dreaming | `dream/instructions.md` tells the dream pass what this memory is for. Edit it. |

### What the agent gets

- **System prompt:** a short description of the memory folder plus `index.md` (first 200 lines / 25 KB at most).
- **Every message:** up to ~3,000 characters of recalled passages, with no tool call needed.
- **Tools:** `mem_search(query, scope)`, `mem_read(path)`, `mem_write(path, content, mode)`.

Built-in `MEMORY.md`/`USER.md` keep working alongside it; writes to them are mirrored into `notes/`.

### The dream pass

```bash
hermes dreaming dream
```

One pass does up to four things, each one model call through Hermes' plugin LLM API (`ctx.llm`:
your configured provider and model, no extra credentials):

1. **verify** — notes and pages changed since the last dream, against the transcript turns that mention them
2. **integrate** — turns not yet dreamed, into wiki pages (in batches of ~28k characters)
3. **links** — only if there are broken `[[links]]`
4. **index** — rewrite `index.md`

In a transcript only what the user said and what tools returned count as evidence. An answer the
agent gave from memory does not, so one wrong answer cannot become a "later fact". A change made by
reference ("everything of hers", a nickname, "what I told you last time") is resolved from the
other sessions and their order. Once a session is dreamed, recall stops showing it raw (the wiki
speaks for it); it stays searchable with `mem_search`.

By default (`auto_dream: true`) a pass also starts in the background when a new session begins and
earlier sessions have un-dreamed turns. A one-shot run (`hermes -z`) can exit before that pass
finishes; nothing is lost, and the pass runs again at the next session. Set `auto_dream` to `false`
to dream only on demand or from a scheduler (for example a nightly `hermes dreaming dream` cron job).

### Commands

These are available while `dreaming` is the active memory provider:

| Command | What it does |
|---|---|
| `hermes dreaming status` | Sessions recorded and pending, memory size, last dream |
| `hermes dreaming dream [--force]` | Run a dream pass now |
| `hermes dreaming search <words>` | Search notes, wiki and transcripts |
| `hermes dreaming show [path]` | Print `index.md`, or any memory file |

## Settings

`<hermes_home>/dreaming/config.json`:

| Key | Default | Meaning |
|---|---|---|
| `auto_dream` | `true` | Dream in the background at session start when work is pending |
| `dream_min_sessions` | `1` | Sessions with un-dreamed turns needed to trigger that |
| `index_max_lines` | `60` | Size the dream pass keeps `index.md` under |
| `prefetch_chars` | `3000` | Per-message recall budget |
| `recall_transcripts` | `true` | Include raw excerpts of not-yet-dreamed sessions in recall |

## Data, safety and disclosure

- **Everything is local.** Memory lives in `<hermes_home>/dreaming/` as plain markdown and JSONL.
  `search.db` is a SQLite FTS5 cache rebuilt from those files, so hand edits are picked up.
- **Network:** the plugin makes no network calls of its own. The dream pass sends transcript
  excerpts and memory files to **your configured model provider**, through Hermes' `ctx.llm`. Nothing
  else leaves the machine. No telemetry.
- **Files:** it reads and writes only its own folder, `<hermes_home>/dreaming/`.
- **Background work:** with `auto_dream` on, a dream pass runs in a background thread at session start.
- **No credentials, no shell commands, no self-updating.**
- **Guard rails on the dream pass:** the model can only return whole-file operations on `index.md`,
  `notes/` and `wiki/`. Transcripts are never writable, pages over 12,000 characters are rejected, and
  memory is copied to `dream/backups/<timestamp>/` (last five kept) before each pass.
  `dream/log.md` records every change.

## License

MIT
