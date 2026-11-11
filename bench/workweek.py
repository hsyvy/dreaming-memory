#!/usr/bin/env python3
"""Test 1: a week of ordinary work chat, then six questions about where things stand now.

    python3 bench/workweek.py all              # the whole test on two new throwaway profiles
    python3 bench/workweek.py chat <profile>   # 14 messages, each one a brand-new `hermes -z` session
    python3 bench/workweek.py ask  <profile>   # 6 questions, each one a brand-new session, graded

`all` recreates `wwstock` (Hermes as shipped) and `wwplugin` (with this plugin), sends both the
same 14 messages, asks both the six questions, runs one dream pass on `wwplugin` and asks it
again. About 75 model calls with your configured model. Delete the profiles afterwards with
`hermes profile delete wwstock -y` and `hermes profile delete wwplugin -y`.

Nothing is edited behind the agent's back. The difficulty is in the data itself: nobody asks
the agent to remember anything, and five facts change the way people actually say such
things, without naming what changed:

    "build 5.8.3 ships the fix for the route cache stampede"      (a blocker closes; no ticket ID)
    "Halvard has taken over everything of hers"                   (ownership moved; no service named)
    "Granny was switched off ... everything is on stg-db-22"      (a host moves; only its nickname)
    "Scrap what I told you last time ... pushed out by one week"  (a date moves; nothing named)
    "they want Tallinn in as well, and Gdansk is out"             (a list changes; no project named)

A keyword search for the question finds the session that stated the fact, not the one that
changed it. The sixth question is a control with no such trap.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "results" / "workweek"
TOOLSETS = "memory,session_search"

CHAT = [
    "The Tidewater launch has two launch blockers right now: TW-2291 (route cache stampede) and TW-2305 "
    "(login timeout). Write a one-line status for the team channel.",
    "While I triage bugs: quaywatch is owned by Sunniva Aaltonen, ledgerd by Priya Raman, harbor-api by "
    "Tomasz Bielak. Give me a one-line template for forwarding a bug to its owner.",
    "The Tidewater staging database is on host stg-db-14, port 6432. What is the psql command to connect "
    "as user tw_app to database tidewater?",
    "Reword this for the release notes in one line: build 5.8.3 ships the fix for the route cache stampede.",
    "The team has started calling stg-db-14 'Granny' because it is so old. Suggest a one-word nickname for "
    "whatever replaces it.",
    "Steering picked the Tidewater launch date today: December 9. How many days is that from November 10?",
    "Scrap what I told you last time: an hour later they pushed it out by exactly one week.",
    "Brightwell Freight's pilot covers their warehouses in Malmö and Gdańsk. Draft a one-line kickoff "
    "greeting to Ingrid Solheim, my contact there.",
    "Sunniva's last day with us was yesterday, and Halvard Lindqvist has taken over everything of hers. "
    "How is 'Lindqvist' pronounced?",
    "Write a one-line thank-you to Priya: her patch landed last night, logins no longer time out, and QA "
    "signed it off.",
    "Granny was switched off this morning. Everything that lived on her is on stg-db-22 now, listening on "
    "6543. What one-liner checks from my laptop that 6543 is reachable there?",
    "Ingrid just emailed: they want Tallinn in as well, and Gdańsk is out until spring. Reply to her in one "
    "line saying that works.",
    "Two more launch blockers as of today: TW-2417 (invoice rounding) and TW-2502 (PDF export crash). "
    "One-line message asking Dario Nkemelu to take both.",
    "Ingrid wants a weekly report every Monday at 09:00. Suggest a three-word subject line for it.",
]

# all: every pattern must match the ANSWER line. none: no pattern may match it.
QUESTIONS = [
    {"id": "blockers", "q": "Which Tidewater launch blockers are still open? Ticket IDs only.",
     "want": "TW-2417, TW-2502", "all": [r"2417", r"2502"], "none": [r"2291", r"2305"]},
    {"id": "owner", "q": "Who owns quaywatch now?",
     "want": "Halvard Lindqvist", "all": [r"halvard"], "none": [r"^\W*sunniva"]},
    {"id": "database", "q": "Which host and port is the Tidewater staging database on?",
     "want": "stg-db-22, 6543", "all": [r"stg-db-22", r"6543"], "none": [r"stg-db-14", r"6432"]},
    {"id": "launch", "q": "What is the Tidewater launch date?",
     "want": "December 16", "all": [r"(dec(ember)?\.? 16\b|\b16(th)? (of )?dec|12-16)"],
     "none": [r"dec(ember)?\.? 0?9\b", r"12-09"]},
    {"id": "pilot", "q": "Which warehouses are in the Brightwell pilot right now?",
     "want": "Malmö, Tallinn", "all": [r"malm", r"tallinn"], "none": [r"gda"]},
    {"id": "report", "q": "When does Ingrid want her weekly report?",
     "want": "Monday 09:00", "all": [r"monday", r"\b0?9([:.]00)?\b"], "none": []},
]

SUFFIX = ("\n\nAnswer from what you know from our earlier sessions. End with one line that starts with "
          "`ANSWER:` and contains only the answer.")


def one_shot(profile: str, prompt: str) -> dict:
    """One brand-new Hermes session: the reply and what it cost."""
    for _attempt in range(2):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            usage_path = fh.name
        started = time.time()
        done = subprocess.run(["hermes", "-p", profile, "-t", TOOLSETS, "--usage-file", usage_path, "-z", prompt],
                              capture_output=True, text=True, timeout=600, cwd=str(Path.home()))
        seconds = time.time() - started
        try:
            usage = json.loads(Path(usage_path).read_text())
        except Exception:
            usage = {}
        Path(usage_path).unlink(missing_ok=True)
        if done.returncode == 0 and done.stdout.strip():
            break
    return {"reply": done.stdout.strip(), "exit": done.returncode, "seconds": round(seconds, 1),
            "api_calls": usage.get("api_calls", 0), "input_tokens": usage.get("input_tokens", 0)}


def answer_line(reply: str) -> str:
    lines = [ln for ln in reply.splitlines() if ln.strip().lstrip("*`> ").upper().startswith("ANSWER:")]
    return lines[-1].split(":", 1)[1].strip(" *`") if lines else " ".join(reply.split())


def grade(question: dict, answer: str) -> bool:
    low = answer.lower()
    return (all(re.search(p, low) for p in question["all"])
            and not any(re.search(p, low) for p in question["none"]))


def save(profile: str, kind: str, rows: list) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%H%M%S")
    (OUT / f"{profile}-{kind}-{stamp}.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))


def chat(profile: str) -> None:
    print(f"{len(CHAT)} messages to `hermes -p {profile}`, each in a brand-new session\n")
    rows = []
    for i, message in enumerate(CHAT, 1):
        result = one_shot(profile, message)
        rows.append({"n": i, "message": message, **result})
        reply = " ".join(result["reply"].split())
        print(textwrap.fill(f"{i:>2} you    {message}", 108, subsequent_indent=" " * 10))
        print(textwrap.fill(f"   hermes {reply}", 108, subsequent_indent=" " * 10, max_lines=2, placeholder=" …"))
        sys.stdout.flush()
    save(profile, "chat", rows)
    print(f"\n{sum(r['api_calls'] for r in rows)} model calls, {sum(r['seconds'] for r in rows):.0f}s")


def ask(profile: str) -> None:
    print(f"{len(QUESTIONS)} questions to `hermes -p {profile}`, each in a brand-new session\n")
    rows, right = [], 0
    for question in QUESTIONS:
        result = one_shot(profile, question["q"] + SUFFIX)
        answer = answer_line(result["reply"])
        ok = grade(question, answer)
        right += ok
        rows.append({**question, "answer": answer, "correct": ok, **result})
        print(question["q"])
        shown = textwrap.shorten(answer, 84, placeholder=" …")
        print(f"   {'✓' if ok else '✗'} {shown}" + ("" if ok else f"      (now: {question['want']})"))
        sys.stdout.flush()
    save(profile, "ask", rows)
    print(f"\n{right}/{len(rows)} correct · {sum(r['api_calls'] for r in rows)} model calls")


def run_all() -> None:
    import run_bench

    stock, plugin = "wwstock", "wwplugin"
    run_bench.fresh_profile(stock, plugin=False)
    run_bench.fresh_profile(plugin, plugin=True)
    for profile in (stock, plugin):
        chat(profile)
    print("\n== stock Hermes")
    ask(stock)
    print("\n== plugin, before any dream pass")
    ask(plugin)
    print("\n== dream pass")
    subprocess.run(["hermes", "-p", plugin, "dreaming", "dream"], check=False)
    print("\n== plugin, after one dream pass")
    ask(plugin)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] in ("chat", "ask"):
        {"chat": chat, "ask": ask}[sys.argv[1]](sys.argv[2])
    elif sys.argv[1:] == ["all"]:
        sys.path.insert(0, str(HERE))
        run_all()
    else:
        sys.exit(__doc__)
