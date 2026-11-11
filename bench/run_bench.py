#!/usr/bin/env python3
"""Live benchmark: the same Hermes, the same model, the same sessions — three memory setups.

    base   Hermes as shipped: built-in MEMORY.md/USER.md + session_search
    raw    + dreaming provider, never dreamed (transcripts, notes, recall)
    dream  + dreaming provider, one dream pass after the sessions

Each arm is its own freshly created Hermes profile, so nothing touches the default profile.
Every session is a separate `hermes -z` one-shot run (a brand-new session each time), so the
only way information crosses from one run to the next is through memory.

    python3 bench/run_bench.py            # full run: ~110 model calls
    python3 bench/run_bench.py --smoke    # 4 sessions, 3 questions
    python3 bench/run_bench.py --report bench/results/<run>   # rebuild report.md from raw.json
"""

from __future__ import annotations

import argparse
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
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import world  # noqa: E402

HERMES_ROOT = Path.home() / ".hermes"
TOOLSETS = "memory,session_search"
ARMS = {"base": "Hermes built-in memory", "raw": "dreaming plugin, no dream", "dream": "dreaming plugin + dream pass"}
PRINT_LOCK = threading.Lock()


def say(arm: str, msg: str) -> None:
    with PRINT_LOCK:
        print(f"[{time.strftime('%H:%M:%S')}] {arm:<5} {msg}", flush=True)


def hermes(profile: str, *args: str, timeout: int = 600, cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["hermes", "-p", profile, *args], capture_output=True, text=True, timeout=timeout, cwd=cwd)


def profile_home(profile: str) -> Path:
    return HERMES_ROOT / "profiles" / profile


def fresh_profile(profile: str, *, plugin: bool) -> None:
    """Delete and recreate a benchmark profile (cloned config and logins, empty memory)."""
    if profile_home(profile).exists():
        subprocess.run(["hermes", "profile", "delete", profile, "-y"], capture_output=True, text=True, timeout=300)
    done = subprocess.run(["hermes", "profile", "create", profile, "--clone", "--no-alias",
                           "--description", "dreaming plugin benchmark arm (safe to delete)"],
                          capture_output=True, text=True, timeout=300)
    if not profile_home(profile).exists():
        raise SystemExit(f"could not create profile {profile}: {done.stdout}{done.stderr}")
    # A cloned profile starts with the default profile's USER.md; the benchmark must start empty.
    for name in ("MEMORY.md", "USER.md"):
        (profile_home(profile) / "memories" / name).unlink(missing_ok=True)
    if plugin:
        dest = profile_home(profile) / "plugins" / "dreaming"
        dest.mkdir(parents=True, exist_ok=True)
        for src in (ROOT / "dreaming").iterdir():
            if src.suffix in (".py", ".yaml", ".md"):
                shutil.copy2(src, dest / src.name)
        store = profile_home(profile) / "dreaming"
        store.mkdir(exist_ok=True)
        (store / "config.json").write_text(json.dumps({"auto_dream": False}))  # the harness dreams explicitly
        out = hermes(profile, "config", "set", "memory.provider", "dreaming")
        if out.returncode != 0:
            raise SystemExit(f"could not activate plugin in {profile}: {out.stdout}{out.stderr}")


def one_shot(profile: str, prompt: str, cwd: str, retries: int = 1, toolsets: str = TOOLSETS) -> dict:
    """One fresh Hermes session; returns the reply and what it cost."""
    for attempt in range(retries + 1):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            usage_path = fh.name
        started = time.time()
        try:
            done = hermes(profile, "-t", toolsets, "--usage-file", usage_path, "-z", prompt, cwd=cwd)
            reply, err, code = done.stdout.strip(), done.stderr.strip(), done.returncode
        except subprocess.TimeoutExpired:
            reply, err, code = "", "timeout", -1
        seconds = time.time() - started
        try:
            usage = json.loads(Path(usage_path).read_text())
        except Exception:
            usage = {}
        Path(usage_path).unlink(missing_ok=True)
        if code == 0 and reply:
            break
    aux = usage.get("auxiliary") or {}
    return {"reply": reply, "seconds": round(seconds, 1), "exit": code, "stderr": err[-400:] if code else "",
            "input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0),
            "api_calls": usage.get("api_calls", 0),
            "aux_calls": aux.get("api_calls", 0), "aux_tokens": aux.get("total_tokens", 0)}


def answer_line(reply: str) -> str:
    lines = [ln for ln in reply.splitlines() if ln.strip().lstrip("*`> ").upper().startswith("ANSWER:")]
    return lines[-1].split(":", 1)[1].strip(" *`") if lines else reply


def grade(question: dict, reply: str) -> bool:
    answer = answer_line(reply).lower()
    return (all(re.search(p, answer, re.I) for p in question["all"])
            and not any(re.search(p, answer, re.I) for p in question.get("none", [])))


def memory_snapshot(arm: str, profile: str, dest: Path) -> dict:
    """Copy the arm's memory (not its sessions) into the results folder and measure it."""
    home = profile_home(profile)
    dest.mkdir(parents=True, exist_ok=True)
    sizes: dict[str, int] = {}
    for name in ("MEMORY.md", "USER.md"):
        src = home / "memories" / name
        sizes[f"builtin {name}"] = src.stat().st_size if src.exists() else 0
        if src.exists():
            shutil.copy2(src, dest / f"builtin-{name}")
    store = home / "dreaming"
    if arm != "base" and store.exists():
        for sub in ("notes", "wiki"):
            files = sorted((store / sub).glob("**/*.md"))
            sizes[f"{sub} files"] = len(files)
            sizes[f"{sub} chars"] = sum(f.stat().st_size for f in files)
            if files:
                shutil.copytree(store / sub, dest / sub, dirs_exist_ok=True)
        index = store / "index.md"
        sizes["index.md chars"] = index.stat().st_size if index.exists() else 0
        sizes["index.md lines"] = len(index.read_text().splitlines()) if index.exists() else 0
        if index.exists():
            shutil.copy2(index, dest / "index.md")
        log = store / "dream" / "log.md"
        if log.exists():
            shutil.copy2(log, dest / "dream-log.md")
        sizes["transcript chars"] = sum(f.stat().st_size for f in (store / "transcripts").glob("*.jsonl"))
    return sizes


def note_files(arm: str, profile: str) -> list[Path]:
    """The files an arm's own notes live in: what the agent wrote, not the transcripts."""
    home = profile_home(profile)
    files = [home / "memories" / "MEMORY.md", home / "memories" / "USER.md"]
    if arm != "base":
        store = home / "dreaming"
        files += [store / "index.md", *sorted((store / "notes").glob("**/*.md")), *sorted((store / "wiki").glob("**/*.md"))]
    return [f for f in files if f.exists()]


def corrupt_in_place(arm: str, profile: str) -> dict:
    """Swap four true values for wrong ones inside the arm's own notes; returns hits per fact."""
    hits = {label: 0 for label, _p, _r in world.CORRUPTIONS}
    for path in note_files(arm, profile):
        text = path.read_text(encoding="utf-8")
        for label, pattern, wrong in world.CORRUPTIONS:
            text, n = re.subn(pattern, wrong, text)
            hits[label] += n
        path.write_text(text, encoding="utf-8")
    return hits


def run_arm(arm: str, profile: str, sessions: list, questions: list, out: Path, results: dict,
            corrupt: str = "planted") -> None:
    record = results[arm] = {"profile": profile, "ingest": [], "questions": [], "dream": None, "memory": {}}
    cwd = tempfile.mkdtemp(prefix=f"dreambench-{arm}-")  # empty dir: no AGENTS.md, no project files
    try:
        fresh_profile(profile, plugin=arm != "base")
        say(arm, f"profile {profile} ready; ingesting {len(sessions)} sessions")
        for i, (date, text) in enumerate(sessions, 1):
            run = one_shot(profile, world.INGEST_PROMPT.format(date=date, text=text), cwd)
            record["ingest"].append({"n": i, "date": date, **run})
            say(arm, f"session {i:>2}/{len(sessions)}  {run['seconds']:>5.1f}s  {run['api_calls']} calls  "
                     f"{'OK' if run['exit'] == 0 else 'FAILED ' + run['stderr'][-120:]}")
        record["memory"]["after sessions"] = memory_snapshot(arm, profile, out / "memory" / arm / "after-sessions")

        if corrupt == "inplace":
            record["corruption"] = corrupt_in_place(arm, profile)
            say(arm, f"corrupted own notes in place: {record['corruption']}")
        elif arm != "base":
            note = profile_home(profile) / "dreaming" / world.PLANTED_NOTE_PATH
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(world.PLANTED_NOTE)
            say(arm, f"planted {world.PLANTED_NOTE_PATH}")
        if arm == "dream":
            started = time.time()
            done = hermes(profile, "dreaming", "dream", "--json", timeout=1800)
            try:
                report = json.loads(done.stdout[done.stdout.index("{"):])
            except ValueError:
                report = {"error": (done.stdout + done.stderr)[-1500:]}
            report["wall_seconds"] = round(time.time() - started, 1)
            record["dream"] = report
            say(arm, f"dream: {report.get('summary') or report.get('error')}")
        record["memory"]["before questions"] = memory_snapshot(arm, profile, out / "memory" / arm / "before-questions")

        for q in questions:
            run = one_shot(profile, world.QUESTION_PROMPT.format(q=q["q"]), cwd)
            ok = grade(q, run["reply"])
            record["questions"].append({"id": q["id"], "group": q["group"], "correct": ok,
                                        "answer": answer_line(run["reply"])[:300], **run})
            say(arm, f"{q['id']:<3} {'✓' if ok else '✗'}  {run['seconds']:>5.1f}s  {run['api_calls']} calls  "
                     f"{answer_line(run['reply'])[:90]!r}")
    except Exception as exc:  # keep the other arms' results
        record["error"] = repr(exc)
        say(arm, f"ARM FAILED: {exc!r}")
    finally:
        shutil.rmtree(cwd, ignore_errors=True)
        (out / "raw.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))


def mean(values: list) -> float:
    return sum(values) / len(values) if values else 0.0


def build_report(out: Path) -> str:
    results = json.loads((out / "raw.json").read_text())
    meta = results.pop("_meta", {})
    arms = [a for a in ARMS if a in results]
    qmeta = {q["id"]: q for q in world.QUESTIONS}
    groups = list(dict.fromkeys(q["group"] for arm in arms for q in results[arm]["questions"]))
    md = [f"# Dreaming memory plugin — benchmark results", "",
          f"Run `{out.name}` · model `{meta.get('model', '?')}` · {meta.get('hermes', '')}", "",
          f"{meta.get('sessions', '?')} project-log sessions, then {meta.get('questions', '?')} questions. Every session and every "
          "question is a separate, brand-new Hermes session (`hermes -z`), so answers can only come from memory. "
          f"All arms use the same toolsets (`{TOOLSETS}`); the only difference is `memory.provider`.", "",
          "| Arm | Setup |", "|---|---|"]
    md += [f"| **{a}** | {ARMS[a]} |" for a in arms]

    md += ["", "## Accuracy", "", "| Question group | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
    for group in groups + ["ALL"]:
        cells = []
        for arm in arms:
            qs = [q for q in results[arm]["questions"] if group == "ALL" or q["group"] == group]
            good = sum(q["correct"] for q in qs)
            cells.append(f"{good}/{len(qs)}" + (f" ({100 * good // len(qs)}%)" if group == "ALL" and qs else ""))
        note = " ¹" if group == "corrupted-note" else ""
        md.append(f"| {'**All questions**' if group == 'ALL' else group + note} | " + " | ".join(cells) + " |")
    if meta.get("corrupt") == "inplace":
        md += ["", "¹ Before the questions (and before the dream pass), four true values were replaced with wrong ones "
                   "inside each arm's own notes: built-in `MEMORY.md` for `base`, the plugin's `notes/` for `raw` and "
                   "`dream`. Transcripts and session history were left intact. Occurrences replaced per arm:", "",
               "| Fact damaged | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
        for label, _p, _r in world.CORRUPTIONS:
            md.append(f"| {label} | " + " | ".join(str((results[a].get("corruption") or {}).get(label, "—")) for a in arms) + " |")
    else:
        md += ["", "¹ One wrong note is planted, only in the two plugin arms (it lives in the plugin's notes folder). "
                   "For `base` this group is plain recall with nothing misleading it."]

    md += ["", "## Cost of answering a question (mean per question)", "",
           "| | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
    rows = [("Model calls", "api_calls", "{:.1f}"), ("Input tokens", "input_tokens", "{:,.0f}"),
            ("Output tokens", "output_tokens", "{:,.0f}"), ("Auxiliary model calls", "aux_calls", "{:.1f}"),
            ("Seconds", "seconds", "{:.1f}")]
    for label, key, fmt in rows:
        md.append(f"| {label} | " + " | ".join(fmt.format(mean([q[key] for q in results[a]["questions"]])) for a in arms) + " |")

    md += ["", "## Cost of remembering", "", "| | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
    md.append("| Model calls over all sessions | " + " | ".join(str(sum(s["api_calls"] for s in results[a]["ingest"])) for a in arms) + " |")
    md.append("| Input tokens over all sessions | " + " | ".join(f"{sum(s['input_tokens'] for s in results[a]['ingest']):,}" for a in arms) + " |")
    md.append("| Seconds over all sessions | " + " | ".join(f"{sum(s['seconds'] for s in results[a]['ingest']):.0f}" for a in arms) + " |")
    dream_cells = []
    for a in arms:
        d = results[a].get("dream")
        dream_cells.append(f"{d.get('llm_calls', '?')} calls, {d.get('wall_seconds', '?')}s" if d else "—")
    md.append("| Dream pass | " + " | ".join(dream_cells) + " |")

    md += ["", "## What each arm had in memory when the questions started", "",
           "| | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
    keys = list(dict.fromkeys(k for a in arms for k in results[a]["memory"].get("before questions", {})))
    for key in keys:
        md.append(f"| {key} | " + " | ".join(
            f"{results[a]['memory'].get('before questions', {}).get(key, '—'):,}"
            if isinstance(results[a]['memory'].get('before questions', {}).get(key), int) else "—" for a in arms) + " |")
    md += ["", f"The memory folders themselves are in `memory/<arm>/` next to this file."]

    dream = (results.get("dream") or {}).get("dream") or {}
    if dream.get("log"):
        md += ["", "## What the dream pass said it changed", ""] + [f"- {line}" for line in dream["log"]]

    md += ["", "## Every question", "", "| id | question | " + " | ".join(arms) + " |", "|---|---|" + "---|" * len(arms)]
    for qid in [q["id"] for q in results[arms[0]]["questions"]]:
        cells = []
        for arm in arms:
            q = next((x for x in results[arm]["questions"] if x["id"] == qid), None)
            cells.append("—" if q is None else ("✓ " if q["correct"] else "✗ ") + q["answer"].replace("|", "\\|").replace("\n", " ")[:110])
        md.append(f"| {qid} | {qmeta[qid]['q']} | " + " | ".join(cells) + " |")
    text = "\n".join(md) + "\n"
    (out / "report.md").write_text(text)
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--smoke", action="store_true", help="tiny run: 4 sessions, 3 questions")
    ap.add_argument("--arms", default="base,raw,dream")
    ap.add_argument("--prefix", default="dream", help="profile name prefix (profiles are deleted and recreated)")
    ap.add_argument("--corrupt", choices=["planted", "inplace"], default="inplace",
                    help="planted: add one wrong note to the plugin arms. inplace: damage four facts inside "
                         "every arm's own notes (default)")
    ap.add_argument("--regrade", help="re-apply the current answer patterns to an existing results folder and exit")
    ap.add_argument("--report", help="rebuild report.md for an existing results folder and exit")
    args = ap.parse_args()
    if args.regrade:
        folder = Path(args.regrade)
        data = json.loads((folder / "raw.json").read_text())
        by_id = {q["id"]: q for q in world.QUESTIONS}
        for arm, rec in data.items():
            for q in rec.get("questions", []) if arm != "_meta" else []:
                new = grade(by_id[q["id"]], q["reply"])
                if new != q["correct"]:
                    print(f"regraded {arm} {q['id']}: {q['correct']} -> {new}  ({q['answer'][:80]!r})")
                    q["correct"] = new
        (folder / "raw.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
        args.report = args.regrade
    if args.report:
        print(build_report(Path(args.report)))
        return

    sessions, questions = world.SESSIONS, world.QUESTIONS
    if args.smoke:
        sessions = [world.SESSIONS[i] for i in (1, 7, 11, 16)]            # staging db, its move, Estuary x2
        questions = [q for q in world.QUESTIONS if q["id"] in ("s1", "c1", "c4")]
    out = HERE / "results" / (time.strftime("%Y%m%d-%H%M%S") + ("-smoke" if args.smoke else ""))
    out.mkdir(parents=True)
    version = subprocess.run(["hermes", "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    model = ""
    for line in (HERMES_ROOT / "config.yaml").read_text().splitlines():
        if line.strip().startswith("default:"):
            model = line.split(":", 1)[1].strip()
            break
    results: dict = {"_meta": {"model": model, "hermes": version, "sessions": len(sessions),
                               "questions": len(questions), "started": time.strftime("%Y-%m-%d %H:%M:%S")}}
    profiles = {"base": f"{args.prefix}base", "raw": f"{args.prefix}raw", "dream": f"{args.prefix}on"}
    results["_meta"]["corrupt"] = args.corrupt
    threads = [threading.Thread(target=run_arm, args=(arm, profiles[arm], sessions, questions, out, results, args.corrupt))
               for arm in args.arms.split(",")]
    for t in threads:
        t.start()
        time.sleep(3)  # stagger profile creation
    for t in threads:
        t.join()
    (out / "raw.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print("\n" + build_report(out))
    print(f"results: {out}")


if __name__ == "__main__":
    main()
