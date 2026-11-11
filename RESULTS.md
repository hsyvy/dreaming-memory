# Results

Three tests of stock Hermes against Hermes with this plugin, run on 2026-11-11 with Hermes Agent
v0.23.1 and `gpt-6.1-sol`. Every chat message and every question is a separate, brand-new Hermes
session, so nothing carries from one to the next except memory. Within a test, the arms differ only
in `memory.provider`.

| Arm | Setup |
|---|---|
| **stock** (also "base") | Hermes as shipped: built-in `MEMORY.md`/`USER.md` + `session_search` |
| **plugin, no dream** (also "raw") | + this plugin, dream pass never run |
| **plugin, after dream** (also "dream") | + this plugin, after a dream pass |

## Summary

| Test | Stock Hermes | Plugin, no dream | Plugin, after dream |
|---|---|---|---|
| 1 · Facts that changed indirectly (correct of 6) | 2, 2, 2 | 2, 2, 3 | **6, 6, 6** |
| 2 · Facts damaged in the agent's own notes (correct of 4) | 2 | 4 | **4** |
| 2 · All 20 questions in that run | 18 | 20 | **20** |
| 3 · Undocumented procedure (model calls per task, tasks 2–6) | 7.4 | 6.6 | **3.0** |
| 3 · Seconds per task (tasks 2–6) | 28.5 | 23.4 | **12.8** |

Test 1 lists three runs. Tests 2 and 3 are one run each.

The tests ran on plugin 0.1.0 (tests 2 and 3) and 0.1.1 (test 1). Version 0.2.0 changes only how
the dream pass reaches the model (through Hermes' public `ctx.llm` instead of an internal module),
checked live; the tests were not rerun on it.

## Test 1 · Facts that changed indirectly ([`bench/workweek.py`](bench/workweek.py))

Fourteen ordinary work messages, each a brand-new session, none asking the agent to remember
anything. Five facts are stated and later changed the way people say such things, without naming
what changed:

| Fact, as first stated | How it changed |
|---|---|
| Launch blockers TW-2291 (route cache stampede), TW-2305 (login timeout) | "build 5.8.3 ships the fix for the route cache stampede"; "her patch landed, logins no longer time out"; then two new blockers |
| quaywatch is owned by Sunniva | "Sunniva's last day was yesterday, Halvard has taken over everything of hers" |
| Staging database on stg-db-14, port 6432 | "we call stg-db-14 'Granny'", then "Granny was switched off … everything is on stg-db-22 now, listening on 6543" |
| Launch date December 9 | "Scrap what I told you last time: … pushed it out by exactly one week" |
| Pilot warehouses Malmö and Gdańsk | "they want Tallinn in as well, and Gdańsk is out until spring" |

Then six questions about the current state (the sixth, a weekly report time, never changes and is
a control). Nothing is edited between the chat and the questions.

Run 3, the one in the [demo video](docs/dreaming-demo.mp4), typed into Hermes' interactive chat:

| Question | Stock Hermes | Plugin, no dream | Plugin, after dream |
|---|---|---|---|
| Open launch blockers | ✗ TW-2291, TW-2305 | ✗ all four | ✓ TW-2417, TW-2502 |
| Who owns quaywatch | ✗ Sunniva Aaltonen | ✓ Halvard Lindqvist | ✓ Halvard Lindqvist |
| Staging database host and port | ✗ stg-db-14:6432 | ✗ stg-db-14:6432 | ✓ stg-db-22:6543 |
| Launch date | ✓ December 16 | ✓ December 16 | ✓ December 16 |
| Warehouses in the pilot | ✗ Malmö, Gdańsk | ✗ Malmö, Gdańsk | ✓ Malmö, Tallinn |
| Weekly report time (control) | ✓ | ✓ | ✓ |
| **Correct** | **2/6** | **3/6** | **6/6** |

Runs 1 and 2 (`hermes -z` one-shot sessions) gave 2/6, 2/6 and 6/6. In run 2 the six questions took
19 model calls for stock Hermes, 13 for the plugin before dreaming and 6 after; the dream pass took 2
model calls and 21 seconds.

Why it comes out this way:

- **Without dreaming, search finds the session that stated the fact and stops there.** "Who owns
  quaywatch" matches the session that said Sunniva owns it. The session that changed it shares no
  word with the question.
- **The dream pass reads all sessions in order**, so it can tell that "everything of hers" means
  quaywatch and that "Granny" is stg-db-14. It writes the current state into wiki pages and a short
  index that every new session starts with. After it, each question took one model call.
- **Catching a change in the moment varies.** In run 3, while handling the Halvard message, the
  plugin agent wrote itself a note that quaywatch had changed owner, so that question was right
  before any dream. In runs 1 and 2 it wrote no note. For "scrap what I told you last time", the
  agent in that session looked up the previous one itself, so every arm got the launch date right in
  all three runs.
- **Neither stock Hermes nor the plugin was told to save anything.** Stock Hermes wrote nothing to
  `MEMORY.md` in any run.

Limits of this test: **the messages were written to produce this result.** Each change deliberately
shares no keyword with its question, and both stock Hermes and this plugin search by keyword. A
memory with embedding search might find some of these without dreaming; that was not tested. Three
runs, 14 messages, six questions, one model. In run 1 one message said Sunniva's last day "is
November 28" (a future date), which made "Sunniva" a defensible answer; it was reworded for runs 2
and 3, with the same scores.

## Test 2 · Recall, and notes that are wrong ([`bench/run_bench.py`](bench/run_bench.py))

24 project-log sessions about a fictional team (including a second project with confusable numbers
and several facts that later sessions change), then 20 questions.

### Run B: four facts damaged inside each arm's own notes

After the sessions, four true values were replaced with wrong ones wherever they appeared in the
arm's own notes (`MEMORY.md` for stock, `notes/` for the plugin). Transcripts and session history
were untouched. The dream arm dreamed after the damage.

| | stock | plugin, no dream | plugin, after dream |
|---|---|---|---|
| Recall | 6/6 | 6/6 | 6/6 |
| Multi-hop | 5/5 | 5/5 | 5/5 |
| Superseded facts | 5/5 | 5/5 | 5/5 |
| Damaged-note facts | 2/4 | 4/4 | 4/4 |
| **All** | **18/20** | **20/20** | **20/20** |
| Model calls per question | 1.8 | 1.5 | **1.1** |
| Input tokens per question | 7,758 | 7,292 | **4,805** |
| Seconds per question | 7.2 | 6.7 | **4.2** |

- **Stock**: only two of the four facts were in `MEMORY.md`, so only two were damaged. It answered
  both wrong, in one call each, straight from the note.
- **Plugin, no dream**: all four were damaged. It answered all four correctly because recall also
  shows the raw transcript, but one question took 5 model calls to resolve the conflict.
- **Plugin, after dream**: the dream pass corrected all four notes, citing the session that proved
  each one, and every question took one call.

Report: [`bench/results/recall-damaged-notes/report.md`](bench/results/recall-damaged-notes/report.md)

### Run A: one wrong note added to the plugin arms only

| | stock | plugin, no dream | plugin, after dream |
|---|---|---|---|
| **All** | 20/20 | 20/20 | 20/20 |
| Model calls per question | 1.6 | 1.4 | **1.1** |
| Input tokens per question | 7,140 | 6,563 | **4,787** |

A separate wrong note sitting next to the agent's own correct notes fooled nobody, which is why run
B damages the notes in place. The dream pass still corrected all four of its claims.

Report: [`bench/results/recall-planted-note/report.md`](bench/results/recall-planted-note/report.md)

Plain recall did not separate the arms: on the 16 recall, multi-hop and superseded-fact questions
every arm scored 16/16 in both runs. At this size, built-in memory plus session search is enough.

## Test 3 · A procedure nobody wrote down ([`bench/run_loop.py`](bench/run_loop.py))

Six tasks, six brand-new sessions: fetch a record with [`bench/vaultctl.py`](bench/vaultctl.py), a
CLI that reveals its requirements one error at a time and never says which realm holds a record.
Nobody asks the agent to remember anything. All 24 answers were correct.

| Model calls per task | no memory | stock | plugin, no dream | plugin, after dream |
|---|---|---|---|---|
| Task 1 | 9 | 9 | 7 | 7 |
| Tasks 2–6, mean | 7.2 | 7.4 | 6.6 | **3.0** |
| Input tokens, tasks 2–6 mean | 22,127 | 28,056 | 30,528 | **14,446** |
| Seconds, tasks 2–6 mean | 27.1 | 28.5 | 23.4 | **12.8** |

The stock and no-dream agents wrote nothing to memory, so they worked the procedure out again every
time. The dream arm ran a dream pass after each task (5 passes, 10 model calls, 93 seconds in total,
not counted above), which wrote a `vaultctl` wiki page and one index line. It still needed 3 calls,
not 1: it tried realms rather than inferring the rule.

Report: [`bench/results/learning-loop/report.md`](bench/results/learning-loop/report.md)

## What memory costs

| | stock | plugin |
|---|---|---|
| Input tokens over the 24 sessions of test 2, run B | 163,506 | 201,387 (no dream), 202,194 (dream) |
| A dream pass | none | 2–3 model calls, 20–70 seconds |
| Always-loaded memory when questions began | 1,917 chars (`MEMORY.md`) | 1,206 chars (`index.md`, 14 lines) |

Sessions with the plugin used about 23% more input tokens, because the memory guidance, the index and
three tool schemas are in every prompt. The saving comes when questions are answered: fewer calls
and tokens per answer after a dream.

## Limits

- **Small runs.** One trial per configuration in tests 2 and 3, three in test 1; no error bars. The
  2/4 against 4/4 comparison rests on two questions.
- **Small scale.** 24 sessions is about 22,000 characters of transcript. Nothing here tests the wiki at
  the scale of thousands of sessions.
- **One model** (`gpt-6.1-sol`) and one Hermes version.
- **The damage in test 2 is synthetic.** Values were swapped by a script, not by an agent making a
  real mistake.
- **Two answer patterns in test 2 were too strict and were corrected, then both runs regraded.** The
  original replies are in each `raw.json`.
- **Spend.** About 900 model calls across all runs.

## Reproduce

Each benchmark creates its own throwaway Hermes profiles (cloned config and logins, empty memory),
uses whatever model Hermes is configured with, and leaves your default profile alone. Delete the
profiles afterwards with `hermes profile delete <name> -y`.

```bash
python3 bench/workweek.py all
```

```bash
python3 bench/run_bench.py --corrupt inplace
```

```bash
python3 bench/run_bench.py --corrupt planted
```

```bash
python3 bench/run_loop.py
```
