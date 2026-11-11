"""Unit tests for the dreaming memory provider. No model calls: the dream pass runs
against a scripted fake LLM. Run with Hermes' own interpreter:

    ./run_tests.sh
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dreaming import DreamingProvider, _tool_digest  # noqa: E402
from dreaming.dream import Dreamer, parse_ops  # noqa: E402
from dreaming.store import MemoryPathError, MemoryStore, chunk_markdown, query_terms  # noqa: E402


class FakeLLM:
    """Plays the model: picks a scripted reply by the TASK line of the prompt."""

    def __init__(self, replies: dict[str, str]):
        self.replies = replies
        self.calls: list[tuple[str, str]] = []

    def __call__(self, messages: list) -> str:
        user = messages[-1]["content"]
        task = user.split("\n", 1)[0]
        for key, reply in self.replies.items():
            if key in task:
                self.calls.append((key, user))
                return reply
        self.calls.append(("?", user))
        return "<<<LOG no changes>>>"

    def prompt(self, key: str) -> str:
        return next(user for k, user in self.calls if k == key)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.tmp.name) / "dreaming")

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_read_delete(self):
        rel = self.store.write("notes/deploy", "# Deploy\nFreeze is on Thursday.")
        self.assertEqual(rel, "notes/deploy.md")
        self.assertIn("Thursday", self.store.read("notes/deploy.md"))
        self.store.write("notes/deploy.md", "Rollback: run `make undo`.", append=True)
        self.assertIn("make undo", self.store.read("notes/deploy"))
        self.assertTrue(self.store.delete("notes/deploy.md"))
        self.assertIsNone(self.store.read("notes/deploy.md"))

    def test_paths_cannot_escape_the_memory_folder(self):
        for bad in ("../etc/passwd", "notes/../../x.md", "transcripts/s1.jsonl", "dream/state.json",
                    "search.db", "/abs/x.md", "notes/"):
            with self.assertRaises(MemoryPathError, msg=bad):
                self.store.write(bad, "x")

    def test_search_finds_notes_wiki_and_transcripts(self):
        self.store.write("wiki/billing-service", "# Billing Service\nOwned by team Kestrel. Port 7443.")
        self.store.write("notes/misc", "# Misc\nThe cafeteria closes at three.")
        self.store.append_turn("s1", "what port does billing listen on?", "Billing listens on 7443.")
        hits = self.store.search("billing port")
        self.assertEqual({h.kind for h in hits}, {"wiki", "transcripts"})
        self.assertEqual(self.store.search("billing", kinds=("wiki",))[0].path, "wiki/billing-service.md")
        self.assertEqual(self.store.search("cafeteria")[0].path, "notes/misc.md")
        self.assertEqual(self.store.search("the and of"), [])

    def test_deleted_file_leaves_search(self):
        self.store.write("notes/gone", "zebra crossing")
        self.assertTrue(self.store.search("zebra"))
        self.store.delete("notes/gone")
        self.assertEqual(self.store.search("zebra"), [])

    def test_sync_picks_up_edits_made_outside_the_store(self):
        (self.store.root / "notes" / "hand.md").write_text("# Hand\nquokka habitat", encoding="utf-8")
        self.assertEqual(self.store.search("quokka"), [])
        self.assertEqual(self.store.sync(), 1)
        self.assertEqual(self.store.search("quokka")[0].path, "notes/hand.md")
        (self.store.root / "notes" / "hand.md").unlink()
        self.store.sync()
        self.assertEqual(self.store.search("quokka"), [])

    def test_transcripts_number_turns_per_session(self):
        self.assertEqual(self.store.append_turn("s1", "a", "b"), 1)
        self.assertEqual(self.store.append_turn("s1", "c", "d", tools=["terminal(ls) -> x"]), 2)
        self.assertEqual(self.store.append_turn("s2", "e", "f"), 1)
        self.assertEqual(self.store.sessions(), {"s1": 2, "s2": 1})
        self.assertIn("TOOL: terminal(ls) -> x", self.store.format_turn(self.store.read_session("s1")[1]))

    def test_broken_links(self):
        self.store.write("wiki/a", "# A\nSee [[b]] and [[Missing Page]] and [[wiki/b|the b page]].")
        self.store.write("wiki/b", "# B\nBack to [[a]].")
        self.assertEqual(self.store.broken_links(), [("wiki/a.md", "Missing Page")])

    def test_index_is_capped_when_loaded(self):
        self.store.write("index.md", "\n".join(f"line {i}" for i in range(500)))
        loaded = self.store.index_text(max_lines=200)
        self.assertIn("line 199", loaded)
        self.assertNotIn("line 200\n", loaded + "\n")
        self.assertIn("truncated", loaded)

    def test_chunking_and_terms(self):
        chunks = chunk_markdown("# Title\nintro\n## Part\n" + ("word " * 800))
        self.assertEqual(chunks[0], ("Title", "intro"))
        self.assertTrue(all(len(body) <= 1500 for _h, body in chunks))
        self.assertEqual(chunks[1][0], "Title › Part")
        self.assertEqual(query_terms("What is the port of the Billing service?"), ["port", "billing", "service"])


class DreamTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.tmp.name) / "dreaming")

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_ops(self):
        files, deletes, logs = parse_ops(
            "chatter\n<<<FILE wiki/a.md>>>\n# A\nbody with <<<DELETE inside>>> text\n<<<END>>>\n"
            "<<<DELETE notes/old.md>>>\n<<<LOG fixed  the\nthing>>>")
        self.assertEqual(files, [("wiki/a.md", "# A\nbody with <<<DELETE inside>>> text")])
        self.assertEqual(deletes, ["notes/old.md"])
        self.assertEqual(logs, ["fixed the thing"])

    def test_dream_corrects_a_note_against_the_transcript(self):
        self.store.append_turn("s1", "When is the deploy freeze?", "The deploy freeze is every Thursday.",
                               ts="2026-11-01T10:00:00")
        self.store.write("notes/deploy", "# Deploy\nThe deploy freeze is every Friday.")
        llm = FakeLLM({
            "verify memory": "<<<FILE notes/deploy.md>>>\n# Deploy\nThe deploy freeze is every Thursday.\n<<<END>>>\n"
                             "<<<LOG deploy freeze is Thursday not Friday (session s1)>>>",
            "integrate new sessions": "<<<FILE wiki/deploy-process.md>>>\n# Deploy Process\nFreeze: every Thursday.\n<<<END>>>\n"
                                      "<<<DELETE notes/deploy.md>>>",
            "rewrite index.md": "<<<FILE index.md>>>\n# Index\n- [[deploy-process]] — freeze day\n<<<END>>>",
        })
        report = Dreamer(self.store, llm).run()

        # the verify prompt carried both the wrong note and the transcript that disproves it
        verify = llm.prompt("verify memory")
        self.assertIn("every Friday", verify)
        self.assertIn("every Thursday", verify)
        self.assertIn("session s1", verify)
        self.assertIn("deploy freeze is Thursday not Friday (session s1)", " ".join(report.log))

        self.assertIsNone(self.store.read("notes/deploy.md"))
        self.assertIn("Thursday", self.store.read("wiki/deploy-process.md"))
        self.assertIn("[[deploy-process]]", self.store.read("index.md"))
        self.assertEqual(report.sessions, ["s1"])
        self.assertEqual(report.llm_calls, 3)
        self.assertEqual(self.store.broken_links(), [])
        self.assertTrue(any((self.store.root / "dream" / "backups").iterdir()))
        self.assertIn("deploy freeze is Thursday", (self.store.root / "dream" / "log.md").read_text())

    def test_second_dream_is_skipped_until_something_changes(self):
        self.store.append_turn("s1", "hello there project", "noted the project")
        llm = FakeLLM({"integrate": "<<<FILE wiki/p.md>>>\n# P\nproject\n<<<END>>>",
                       "rewrite index.md": "<<<FILE index.md>>>\n- [[p]]\n<<<END>>>"})
        dreamer = Dreamer(self.store, llm)
        self.assertFalse(dreamer.run().skipped)
        calls = len(llm.calls)
        self.assertTrue(dreamer.run().skipped)
        self.assertEqual(len(llm.calls), calls)

        self.store.append_turn("s1", "one more thing about the project", "ok")   # new turn in an old session
        self.assertEqual(dreamer.pending(), {"s1": (1, 2)})
        dreamer.run()
        integrate = [user for key, user in llm.calls if key == "integrate"][-1]
        self.assertIn("one more thing", integrate)
        self.assertNotIn("hello there project", integrate.split("NEW TRANSCRIPT TURNS")[1])

        self.store.write("notes/new", "the agent wrote this about the project")  # a changed note re-triggers verify
        self.assertEqual(dreamer.unverified(), ["notes/new.md"])

    def test_current_session_is_not_dreamed(self):
        self.store.append_turn("live", "in progress", "…")
        self.assertEqual(Dreamer(self.store, FakeLLM({})).pending(exclude_session="live"), {})

    def test_bad_model_output_cannot_damage_the_store(self):
        self.store.append_turn("s1", "topic alpha", "alpha is 1")
        llm = FakeLLM({
            "integrate": "<<<FILE ../../outside.md>>>\nx\n<<<END>>>\n"
                         "<<<FILE transcripts/s1.jsonl>>>\nrewritten history\n<<<END>>>\n"
                         "<<<FILE wiki/huge.md>>>\n" + ("x" * 20000) + "\n<<<END>>>\n"
                         "<<<DELETE index.md>>>\n<<<DELETE dream/state.json>>>\n"
                         "<<<FILE wiki/ok.md>>>\n# OK\nalpha is 1\n<<<END>>>",
            "rewrite index.md": "<<<FILE index.md>>>\n" + "\n".join(f"l{i}" for i in range(300)) + "\n<<<END>>>\n"
                                "<<<FILE wiki/sneak.md>>>\nnot allowed in this phase\n<<<END>>>",
        })
        report = Dreamer(self.store, llm, index_max_lines=40).run()
        self.assertEqual(self.store.files(), ["index.md", "wiki/ok.md"])
        self.assertFalse((Path(self.tmp.name) / "outside.md").exists())
        self.assertIn("alpha is 1", self.store.read_session("s1")[0]["assistant"])
        self.assertEqual(len(self.store.read("index.md").splitlines()), 40)
        self.assertEqual(sum("rejected" in line for line in report.log), 4)

    def test_lock_left_by_a_dead_process_is_released(self):
        import subprocess
        dreamer = Dreamer(self.store, FakeLLM({}))
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        dreamer.lock_path.parent.mkdir(parents=True, exist_ok=True)
        dreamer.lock_path.write_text(str(dead.pid))
        self.assertTrue(dreamer._acquire())
        dreamer.lock_path.unlink()

    def test_lock_held_by_a_live_process_is_respected(self):
        dreamer = Dreamer(self.store, FakeLLM({}))
        dreamer.lock_path.parent.mkdir(parents=True, exist_ok=True)
        dreamer.lock_path.write_text(str(os.getpid()))
        self.assertFalse(dreamer._acquire())
        dreamer.lock_path.unlink()

    def test_dream_repairs_broken_links(self):
        self.store.append_turn("s1", "tell me about kestrel", "Kestrel owns billing.")
        llm = FakeLLM({
            "integrate": "<<<FILE wiki/billing.md>>>\n# Billing\nOwned by [[team-kestrel]].\n<<<END>>>",
            "repair links": "<<<FILE wiki/team-kestrel.md>>>\n# Team Kestrel\nOwns [[billing]].\n<<<END>>>",
            "rewrite index.md": "<<<FILE index.md>>>\n- [[billing]]\n- [[team-kestrel]]\n<<<END>>>",
        })
        Dreamer(self.store, llm).run()
        self.assertIn("[[team-kestrel]] (linked from wiki/billing.md)", llm.prompt("repair links"))
        self.assertEqual(self.store.broken_links(), [])

    def test_goal_instructions_reach_the_model(self):
        self.store.append_turn("s1", "contract terms matter", "ok")
        dreamer = Dreamer(self.store, lambda messages: seen.append(messages[0]["content"]) or "<<<LOG no changes>>>")
        seen: list[str] = []
        dreamer.instructions_path.write_text("Quote contract terms word for word.", encoding="utf-8")
        dreamer.run()
        self.assertTrue(seen and all("Quote contract terms word for word." in s for s in seen))


class ProviderTests(unittest.TestCase):
    """Drive the provider through Hermes' real MemoryManager."""

    def setUp(self):
        from agent.memory_manager import MemoryManager

        # The manager only serves callers in the profile the provider was initialized for,
        # so the test runs inside the HERMES_HOME that run_tests.sh created.
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ["HERMES_HOME"])
        self.home = Path(os.environ["HERMES_HOME"])
        shutil.rmtree(self.home / "dreaming", ignore_errors=True)
        (self.home / "dreaming").mkdir()
        (self.home / "dreaming" / "config.json").write_text(json.dumps({"auto_dream": False}))
        self.provider = DreamingProvider()
        self.mgr = MemoryManager()
        self.mgr.add_provider(self.provider)
        self.mgr.initialize_all(session_id="sess-1", platform="cli")

    def tearDown(self):
        self.mgr.shutdown_all()
        self.tmp.cleanup()

    def call(self, tool, **args):
        return json.loads(self.mgr.handle_tool_call(tool, args))

    def test_tools_are_exposed_and_routed(self):
        names = {schema["name"] for schema in self.mgr.get_all_tool_schemas()}
        self.assertEqual(names, {"mem_search", "mem_read", "mem_write"})
        self.assertEqual(self.call("mem_write", path="notes/prefs", content="User prefers metric units.")["saved"],
                         "notes/prefs.md")
        self.assertIn("metric", self.call("mem_read", path="notes/prefs")["content"])
        self.assertEqual(self.call("mem_search", query="metric units")["results"][0]["path"], "notes/prefs.md")
        self.assertIn("notes/prefs.md", self.call("mem_read")["files"])
        self.assertIn("error", self.call("mem_write", path="../x.md", content="nope"))
        self.assertTrue(self.call("mem_write", path="notes/prefs.md", content="")["deleted"])

    def test_index_is_injected_into_the_system_prompt(self):
        self.assertIn("nothing has been promoted", self.mgr.build_system_prompt())
        self.call("mem_write", path="index.md", content="# Index\n- User's name is Ada.")
        prompt = self.mgr.build_system_prompt()
        self.assertIn("User's name is Ada.", prompt)
        self.assertIn("mem_search", prompt)

    def test_turns_are_recorded_and_recalled_in_a_later_session(self):
        self.mgr.sync_all("The staging database lives on host db-stg-04.", "Understood: db-stg-04.",
                          session_id="sess-1",
                          messages=[{"role": "user", "content": "x"},
                                    {"role": "assistant", "tool_calls": [
                                        {"id": "c1", "function": {"name": "terminal", "arguments": "{\"cmd\": \"ping db-stg-04\"}"}}]},
                                    {"role": "tool", "tool_call_id": "c1", "content": "64 bytes from db-stg-04"}])
        self.assertTrue(self.mgr.flush_pending(timeout=10))
        row = self.provider._store.read_session("sess-1")[0]
        self.assertEqual(row["turn"], 1)
        self.assertIn("ping db-stg-04", row["tools"][0])

        # same session: its own transcript is already in context, so it is not recalled
        self.assertEqual(self.mgr.prefetch_all("which host is the staging database on?", session_id="sess-1"), "")
        recalled = self.mgr.prefetch_all("which host is the staging database on?", session_id="sess-2")
        self.assertIn("db-stg-04", recalled)
        self.assertIn("Dreaming", self.mgr.describe_recall())

    def test_wiki_outranks_raw_transcripts_in_recall(self):
        self.provider._store.write("wiki/staging-db", "# Staging DB\nHost: db-stg-09 (moved from db-stg-04).")
        self.provider._store.append_turn("old", "staging database host?", "db-stg-04")
        recalled = self.mgr.prefetch_all("staging database host", session_id="sess-2")
        self.assertLess(recalled.index("wiki/staging-db.md"), recalled.index("Past session excerpts"))

    def test_consolidated_turns_are_not_recalled_raw(self):
        store = self.provider._store
        store.write("wiki/staging-db", "# Staging DB\nHost: db-stg-09.")
        store.append_turn("old", "staging database host?", "db-stg-04")
        store.append_turn("new", "the staging database host is db-stg-09 now", "ok")
        (store.root / "dream").mkdir(exist_ok=True)
        (store.root / "dream" / "state.json").write_text(json.dumps({"dreamed": {"old": 1}}))
        recalled = self.mgr.prefetch_all("staging database host", session_id="sess-2")
        self.assertIn("db-stg-09 now", recalled)          # not dreamed yet: still shown raw
        self.assertNotIn("db-stg-04", recalled)           # dreamed: the wiki speaks for it
        self.assertTrue(store.search("db-stg-04", kinds=("transcripts",)))   # but still searchable

    def test_builtin_memory_writes_are_mirrored(self):
        self.provider.on_memory_write("add", "user", "Prefers terse answers.")
        self.assertIn("(user) Prefers terse answers.", self.provider._store.read("notes/from-builtin-memory.md"))

    def test_subagents_do_not_write(self):
        from agent.memory_manager import MemoryManager

        provider = DreamingProvider()
        mgr = MemoryManager()
        mgr.add_provider(provider)
        mgr.initialize_all(session_id="child", platform="cli", agent_context="subagent")
        provider.sync_turn("u", "a", session_id="child")
        self.assertEqual(provider._store.sessions(), {})
        self.assertIn("error", json.loads(provider.handle_tool_call("mem_write", {"path": "notes/x", "content": "y"})))
        mgr.shutdown_all()

    def test_tool_digest_keeps_only_the_last_turn_and_skips_memory_reads(self):
        messages = [
            {"role": "user", "content": "old"},
            {"role": "assistant", "tool_calls": [{"id": "a", "function": {"name": "terminal", "arguments": "old"}}]},
            {"role": "tool", "tool_call_id": "a", "content": "old result"},
            {"role": "user", "content": "new"},
            {"role": "assistant", "tool_calls": [{"id": "b", "function": {"name": "mem_read", "arguments": "{}"}},
                                                 {"id": "c", "function": {"name": "terminal", "arguments": "date"}}]},
            {"role": "tool", "tool_call_id": "b", "content": "memory"},
            {"role": "tool", "tool_call_id": "c", "content": "Wed Nov 11"},
        ]
        self.assertEqual(_tool_digest(messages), ["terminal(date) -> Wed Nov 11"])



class ModelRoutingTests(unittest.TestCase):
    """The dream pass reaches the model only through Hermes' plugin LLM API (ctx.llm)."""

    class FakeCtx:
        def __init__(self):
            self.calls = []
            self.providers = []
            outer = self

            class Llm:
                def complete(self, messages, **kw):
                    outer.calls.append((messages, kw))
                    return type("Result", (), {"text": "<<<LOG ok>>>"})()

            self.llm = Llm()

        def register_memory_provider(self, provider):
            self.providers.append(provider)

    def test_register_hands_ctx_llm_to_the_dream_pass(self):
        import dreaming
        from dreaming.dream import hermes_llm

        ctx = self.FakeCtx()
        dreaming.register(ctx)
        self.assertEqual(len(ctx.providers), 1)
        self.assertIs(dreaming._LLM, ctx.llm)
        reply = hermes_llm([{"role": "user", "content": "TASK: x"}], dreaming._LLM)
        self.assertEqual(reply, "<<<LOG ok>>>")
        self.assertEqual(ctx.calls[0][1]["purpose"], "dreaming.dream")

    def test_no_private_hermes_imports(self):
        for path in (ROOT / "dreaming").glob("*.py"):
            self.assertNotIn("auxiliary_client", path.read_text(), path.name)


if __name__ == "__main__":
    unittest.main()
