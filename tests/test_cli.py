import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, build_world, controlled_env


def cli(args, cwd, timeout=90):
    env = controlled_env()
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run([sys.executable, "-m", "bugjar"] + args,
                          cwd=str(cwd), env=env, capture_output=True,
                          text=True, timeout=timeout)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bugjar-cli-")
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.world = build_world(self.dir / "world")

    def command(self):
        return [sys.executable, "probe.py"]

    def test_run_verify_doctor_json(self):
        r = cli(["run", "--root", "world", "--out", "run.bugjar", "--json",
                 "--"] + self.command(), self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run_doc = json.loads(r.stdout)
        self.assertEqual(run_doc["inputs"], 10)

        v = cli(["verify", "run.bugjar", "--json"], self.dir)
        self.assertEqual(v.returncode, 0, v.stdout + v.stderr)
        self.assertEqual(json.loads(v.stdout)["verdict"], "REPRODUCED")

        d = cli(["doctor", "run.bugjar", "--json"], self.dir)
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        self.assertTrue(json.loads(d.stdout)["comparable"])

    def test_shrink_cli_json_is_deterministic(self):
        cli(["run", "--root", "world", "--out", "run.bugjar", "--json",
             "--"] + self.command(), self.dir)
        a = cli(["shrink", "run.bugjar", "--out", "m1.bugjar", "--budget", "120", "--json"], self.dir)
        b = cli(["shrink", "run.bugjar", "--out", "m2.bugjar", "--budget", "120", "--json"], self.dir)
        self.assertEqual(a.returncode, 0, a.stdout + a.stderr)
        self.assertEqual(b.returncode, 0, b.stdout + b.stderr)
        da, db = json.loads(a.stdout), json.loads(b.stdout)
        self.assertEqual(da["kept_units"], db["kept_units"])
        self.assertEqual(da["oracle_calls"], db["oracle_calls"])
        self.assertEqual(da["verdict"], "SHRUNK")

    def test_diff_and_explain(self):
        build_world(self.dir / "other", data="world")
        cli(["run", "--root", "world", "--out", "a.bugjar", "--json", "--"] + self.command(), self.dir)
        cli(["run", "--root", "other", "--out", "b.bugjar", "--json", "--"] + self.command(), self.dir)
        d = cli(["diff", "a.bugjar", "b.bugjar", "--json"], self.dir)
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        self.assertGreater(json.loads(d.stdout)["change_count"], 0)
        e = cli(["explain", "a.bugjar"], self.dir)
        self.assertEqual(e.returncode, 0, e.stdout + e.stderr)
        self.assertIn("[evidence:", e.stdout)

    def test_version(self):
        r = cli(["version"], self.dir)
        self.assertEqual(r.returncode, 0)
        self.assertIn("bugjar", r.stdout)

    def test_sign_and_verify_key(self):
        (self.dir / "key.bin").write_bytes(b"local-shared-key-0123456789")
        r = cli(["run", "--root", "world", "--out", "s.bugjar", "--json",
                 "--sign", "key.bin", "--"] + self.command(), self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(json.loads(r.stdout)["signed"])
        good = cli(["verify", "s.bugjar", "--json", "--key", "key.bin"], self.dir)
        self.assertEqual(json.loads(good.stdout)["verdict"], "REPRODUCED")
        (self.dir / "wrong.bin").write_bytes(b"not-the-key")
        bad = cli(["verify", "s.bugjar", "--json", "--key", "wrong.bin"], self.dir)
        self.assertEqual(json.loads(bad.stdout)["verdict"], "UNVERIFIABLE")

    def test_cli_rejects_missing_command(self):
        r = cli(["run", "--root", "world", "--out", "x.bugjar", "--json", "--"], self.dir)
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
