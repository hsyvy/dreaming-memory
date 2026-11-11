#!/usr/bin/env python3
"""Learning-loop benchmark: does a procedure worked out the hard way survive to the next session?

Six tasks, each a brand-new Hermes session: "fetch record N with vaultctl.py". The tool only
reveals its requirements one error at a time, and the rule for which realm holds a record is
never stated. A session with no memory rediscovers all of it every time; a session with
memory should need fewer and fewer model calls.

    none   no memory tools at all (stateless)
    base   Hermes built-in memory + session_search
    raw    dreaming plugin, never dreamed
    dream  dreaming plugin, dream pass after every task

    python3 bench/run_loop.py
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_bench as rb  # noqa: E402
import vaultctl  # noqa: E402

RECORDS = ["4127", "5302", "6815", "7240", "8356", "9469"]   # archive, north, south, north, south, archive
ARMS = {"none": "no memory (stateless)", "base": "Hermes built-in memory",
        "raw": "dreaming plugin, no dream", "dream": "dreaming plugin + dream after each task"}
PROMPT = ("Use the command-line tool `python3 {tool}` to fetch record {record} and tell me its value. "
          "End with one line that starts with `ANSWER:` and contains only the value.")


def run_arm(arm: str, profile: str, out: Path, results: dict) -> None:
    record = results[arm] = {"profile": profile, "tasks": [], "dreams": []}
    cwd = tempfile.mkdtemp(prefix=f"dreamloop-{arm}-")
    toolsets = "terminal" if arm == "none" else "terminal,memory,session_search"
    try:
        rb.fresh_profile(profile, plugin=arm in ("raw", "dream"))
        for i, rec in enumerate(RECORDS, 1):
            run = rb.one_shot(profile, PROMPT.format(tool=HERE / "vaultctl.py", record=rec), cwd, toolsets=toolsets)
            answer = rb.answer_line(run["reply"])
            ok = bool(re.search(re.escape(vaultctl.value_of(rec)), answer))
            record["tasks"].append({"n": i, "record": rec, "correct": ok, "answer": answer[:120], **run})
            rb.say(arm, f"task {i}/6 record {rec} {'✓' if ok else '✗'}  {run['api_calls']} calls  {run['seconds']}s")
            if arm == "dream" and i < len(RECORDS):
                started = time.time()
                done = rb.hermes(profile, "dreaming", "dream", "--json", timeout=1800)
                try:
                    report = json.loads(done.stdout[done.stdout.index("{"):])
                except ValueError:
                    report = {"error": (done.stdout + done.stderr)[-800:]}
                record["dreams"].append({"llm_calls": report.get("llm_calls"), "seconds": round(time.time() - started, 1),
                                         "summary": report.get("summary") or report.get("error")})
                rb.say(arm, f"dream: {report.get('summary') or report.get('error')}")
        record["memory"] = rb.memory_snapshot("base" if arm in ("none", "base") else arm, profile, out / "memory" / arm)
    except Exception as exc:
        record["error"] = repr(exc)
        rb.say(arm, f"ARM FAILED: {exc!r}")
    finally:
        shutil.rmtree(cwd, ignore_errors=True)
        (out / "raw.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))


def build_report(out: Path) -> str:
    results = json.loads((out / "raw.json").read_text())
    meta = results.pop("_meta", {})
    arms = [a for a in ARMS if a in results]
    md = ["# Learning loop — results", "",
          f"Run `{out.name}` · model `{meta.get('model', '?')}` · {meta.get('hermes', '')}", "",
          "Six tasks in six brand-new sessions: fetch a record with an awkward CLI whose rules are only "
          "revealed by trial and error. Fewer model calls on later tasks means the procedure was remembered.", "",
          "| Arm | Setup |", "|---|---|"] + [f"| **{a}** | {ARMS[a]} |" for a in arms]
    md += ["", "## Model calls per task (✗ = wrong value)", "",
           "| Task | record | " + " | ".join(arms) + " |", "|---|---|" + "---|" * len(arms)]
    for i, rec in enumerate(RECORDS):
        cells = []
        for a in arms:
            t = results[a]["tasks"][i] if i < len(results[a]["tasks"]) else None
            cells.append("—" if t is None else f"{t['api_calls']}{'' if t['correct'] else ' ✗'}")
        md.append(f"| {i + 1} | {rec} | " + " | ".join(cells) + " |")

    def col(fn, fmt="{:.1f}"):
        return " | ".join(fmt.format(fn(results[a]["tasks"])) if results[a]["tasks"] else "—" for a in arms)

    md += ["", "## Summary", "", "| | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms),
           "| Correct | " + col(lambda ts: sum(t["correct"] for t in ts), "{}/6") + " |",
           "| Model calls, task 1 | " + col(lambda ts: ts[0]["api_calls"], "{}") + " |",
           "| Model calls, mean of tasks 2–6 | " + col(lambda ts: rb.mean([t["api_calls"] for t in ts[1:]])) + " |",
           "| Input tokens, mean of tasks 2–6 | " + col(lambda ts: rb.mean([t["input_tokens"] for t in ts[1:]]), "{:,.0f}") + " |",
           "| Seconds, mean of tasks 2–6 | " + col(lambda ts: rb.mean([t["seconds"] for t in ts[1:]])) + " |"]
    dreams = (results.get("dream") or {}).get("dreams") or []
    if dreams:
        md += ["", f"Dream passes in the `dream` arm: {len(dreams)}, "
                   f"{sum(d['llm_calls'] or 0 for d in dreams)} model calls, {sum(d['seconds'] for d in dreams):.0f}s in total "
                   "(run between tasks, not counted in the per-task numbers)."]
    text = "\n".join(md) + "\n"
    (out / "report.md").write_text(text)
    return text


def main() -> None:
    if len(sys.argv) > 2 and sys.argv[1] == "--report":
        print(build_report(Path(sys.argv[2])))
        return
    out = HERE / "results" / (time.strftime("%Y%m%d-%H%M%S") + "-loop")
    out.mkdir(parents=True)
    version = subprocess.run(["hermes", "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    model = next((ln.split(":", 1)[1].strip() for ln in (rb.HERMES_ROOT / "config.yaml").read_text().splitlines()
                  if ln.strip().startswith("default:")), "")
    results: dict = {"_meta": {"model": model, "hermes": version}}
    threads = [threading.Thread(target=run_arm, args=(arm, f"loop{arm}", out, results)) for arm in ARMS]
    for t in threads:
        t.start()
        time.sleep(3)
    for t in threads:
        t.join()
    (out / "raw.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print("\n" + build_report(out))
    print(f"results: {out}")


if __name__ == "__main__":
    main()
