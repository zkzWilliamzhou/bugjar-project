import json
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import (ROOT, argv, build_world, controlled_env, resign)
from bugjar import cassette, engine, util


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bugjar-engine-")
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.world = build_world(self.dir / "world")
        self.out = self.dir / "run.bugjar"
        self.env = controlled_env()

    def capture(self, out=None, world=None, env=None, **kw):
        return engine.run(world or self.world, argv(), out or self.out,
                          env_base=env or self.env, timeout=10.0, **kw)

    def test_run_records_inputs_and_outputs(self):
        s = self.capture()
        self.assertEqual(s["observation"]["exit_code"], 0)
        self.assertEqual(s["inputs"], 10)
        self.assertEqual(s["redactions"], 0)
        self.assertEqual(s["caveats"], 0)
        self.assertEqual(s["observation"]["created"], 1)
        self.assertTrue((self.out).is_file())
        m, _ = cassette.load(self.out)
        self.assertEqual(m["format"], "bugjar/1")
        self.assertIn("result.txt", m["observation"]["created"])

    def test_verify_reproduced(self):
        self.capture()
        r = engine.verify(self.out, repeat=1, timeout=10.0)
        self.assertEqual(r["verdict"], "REPRODUCED", r)
        self.assertEqual(r["integrity"], "ok")
        self.assertEqual(r["profile"], "comparable")
        self.assertEqual(len(r["channels"]), 7)
        self.assertTrue(all(c["match"] for c in r["channels"].values()))

    def test_verify_repeat_two(self):
        self.capture()
        r = engine.verify(self.out, repeat=2, timeout=10.0)
        self.assertEqual(r["verdict"], "REPRODUCED")
        self.assertEqual(r["repeats"], 2)

    def test_forged_observation_yields_diverged(self):
        self.capture()
        resign(self.out, lambda m: m["observation"].update(exit_code=99))
        r = engine.verify(self.out, repeat=1, timeout=10.0)
        self.assertEqual(r["verdict"], "DIVERGED", r)
        self.assertFalse(r["channels"]["exit_code"]["match"])
        self.assertEqual(r["channels"]["exit_code"]["recorded"], 99)

    def test_changed_stdout_yields_diverged(self):
        self.capture()
        resign(self.out, lambda m: m["observation"]["stdout"].update(size=999))
        r = engine.verify(self.out, repeat=1, timeout=10.0)
        self.assertEqual(r["verdict"], "DIVERGED")
        self.assertIn("stdout", [c for c, v in r["channels"].items() if not v["match"]])

    def test_corrupt_cassette_yields_unverifiable_not_exception(self):
        self.capture()
        data = bytearray(self.out.read_bytes())
        mid = len(data) // 2
        data[mid] ^= 0x01
        self.out.write_bytes(bytes(data))
        r = engine.verify(self.out, repeat=1, timeout=10.0)
        self.assertEqual(r["verdict"], "UNVERIFIABLE", r)
        self.assertEqual(r["integrity"], "failed")
        self.assertTrue(r["reasons"])

    def test_profile_mismatch_yields_unverifiable(self):
        self.capture()
        resign(self.out, lambda m: m["profile"].update(machine="s390x-impossible"))
        r = engine.verify(self.out, repeat=1, timeout=10.0)
        self.assertEqual(r["verdict"], "UNVERIFIABLE", r)
        self.assertTrue(any("profile" in x.lower() for x in r["reasons"]), r["reasons"])

    def test_redacted_env_yields_unverifiable_by_default(self):
        self.capture(env=controlled_env({"API_TOKEN": "hunter2"}))
        r = engine.verify(self.out, repeat=1, timeout=10.0)
        self.assertEqual(r["verdict"], "UNVERIFIABLE", r)
        self.assertTrue(any("redact" in x.lower() for x in r["reasons"]), r["reasons"])
        m, _ = cassette.load(self.out)
        self.assertEqual(m["environment"]["redactions"][0]["key"], "API_TOKEN")
        self.assertNotIn("hunter2", json.dumps(m))

    def test_allow_redacted_weakens_explicitly(self):
        self.capture(env=controlled_env({"API_TOKEN": "hunter2"}))
        r = engine.verify(self.out, repeat=1, timeout=10.0, allow_redacted=True)
        self.assertEqual(r["verdict"], "REPRODUCED", r)
        self.assertTrue(any("redact" in c.lower() for c in r["caveats"]), r["caveats"])

    def test_shrink_removes_noise_and_reverifies(self):
        self.capture()
        minimal = self.dir / "min.bugjar"
        s = engine.shrink(self.out, minimal, budget=200, timeout=10.0)
        self.assertEqual(s["verdict"], "SHRUNK", s)
        self.assertTrue(s["reverified"])
        kept = set(s["kept_units"])
        self.assertIn("data.txt", kept)
        self.assertFalse(any(x.startswith("noise_") for x in kept), kept)
        self.assertGreaterEqual(len(s["removed_units"]), 8)
        self.assertGreater(s["oracle_calls"], 0)
        self.assertTrue(minimal.is_file())
        r = engine.verify(minimal, repeat=1, timeout=10.0)
        self.assertEqual(r["verdict"], "REPRODUCED", r)

    def test_shrink_respects_budget(self):
        self.capture()
        minimal = self.dir / "min2.bugjar"
        s = engine.shrink(self.out, minimal, budget=1, timeout=10.0)
        self.assertEqual(s["verdict"], "BUDGET_EXHAUSTED", s)
        self.assertFalse(minimal.exists())

    def test_shrink_preserves_failure_signature(self):
        world = build_world(self.dir / "boom", data="BOOM")
        out = self.dir / "boom.bugjar"
        self.capture(out=out, world=world)
        minimal = self.dir / "boom.min.bugjar"
        s = engine.shrink(out, minimal, budget=200, timeout=10.0)
        self.assertEqual(s["verdict"], "SHRUNK", s)
        m, _ = cassette.load(minimal)
        self.assertEqual(m["observation"]["exit_code"], 3)

    def test_diff_reports_changed_channels(self):
        other = build_world(self.dir / "other", data="world")
        out2 = self.dir / "run2.bugjar"
        self.capture()
        engine.run(other, argv(), out2, env_base=self.env, timeout=10.0)
        d = engine.diff(self.out, out2)
        self.assertGreater(d["change_count"], 0)
        paths = {c["path"] for c in d["changes"]}
        self.assertTrue(any("stdout" in p for p in paths), paths)
        self.assertTrue(any("inputs" in p for p in paths), paths)

    def test_explain_is_evidence_linked(self):
        self.capture()
        text = engine.explain(self.out)
        self.assertIn("[evidence:", text)
        self.assertIn("exit_code", text)
        self.assertIn("Caveats", text)
        self.assertNotIn("game-changer", text)
        self.assertNotIn("Here's the thing", text)

    def test_doctor_reports_mismatch(self):
        self.capture()
        d = engine.doctor(self.out)
        self.assertTrue(d["comparable"], d)
        resign(self.out, lambda m: m["profile"].update(python="0.0"))
        d = engine.doctor(self.out)
        self.assertFalse(d["comparable"])
        self.assertTrue(any("python" in x for x in d["mismatches"]))

    def test_timeout_yields_unverifiable(self):
        self.capture()
        resign(self.out, lambda m: m["command"].update(
            argv=[sys.executable, "-c", "import time; time.sleep(5)"]))
        r = engine.verify(self.out, repeat=1, timeout=0.2)
        self.assertEqual(r["verdict"], "UNVERIFIABLE", r)
        self.assertTrue(any("timeout" in x.lower() for x in r["reasons"]), r["reasons"])

    def test_repeat_split_is_unverifiable(self):
        self.capture()
        # Two replays that disagree with each other must never be majority-voted.
        resign(self.out, lambda m: m["command"].update(
            argv=[sys.executable, "-c", "import os,sys; sys.stdout.write(os.urandom(8).hex())"]))
        r = engine.verify(self.out, repeat=2, timeout=10.0)
        self.assertEqual(r["verdict"], "UNVERIFIABLE", r)
        self.assertTrue(any("nondetermin" in x.lower() for x in r["reasons"]), r["reasons"])


class SourceHygieneTests(unittest.TestCase):
    def test_no_shell_true_and_no_third_party_runtime_imports(self):
        import ast
        allowed = set(getattr(sys, "stdlib_module_names", ())) | {
            "bugjar", "__future__", "argparse", "ast", "base64", "contextlib",
            "dataclasses", "datetime", "hashlib", "hmac", "io", "json", "os",
            "pathlib", "platform", "re", "resource", "shutil", "stat",
            "subprocess", "sys", "tempfile", "textwrap", "time", "typing",
            "unicodedata", "zipfile",
        }
        for py in sorted((ROOT / "bugjar").glob("*.py")):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    for kw in node.keywords:
                        self.assertNotEqual(kw.arg, "shell", "%s uses shell=" % py.name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertIn(alias.name.split(".")[0], allowed,
                                      "%s imports %s" % (py.name, alias.name))
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    self.assertIn(node.module.split(".")[0], allowed,
                                  "%s imports %s" % (py.name, node.module))


if __name__ == "__main__":
    unittest.main()
