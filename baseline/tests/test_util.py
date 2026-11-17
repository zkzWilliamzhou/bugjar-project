import json
import unittest

from helpers import ROOT
from bugjar import util


class CanonicalJsonTests(unittest.TestCase):
    def test_key_order_does_not_matter(self):
        a = {"b": 1, "a": {"d": 2, "c": 3}}
        b = {"a": {"c": 3, "d": 2}, "b": 1}
        self.assertEqual(util.canonical_json(a), util.canonical_json(b))

    def test_is_compact_ascii(self):
        out = util.canonical_json({"k": "caf\u00e9"})
        self.assertNotIn(b" ", out)
        self.assertIn(b"caf\\u00e9", out)

    def test_rejects_non_json_types(self):
        with self.assertRaises(TypeError):
            util.canonical_json({"x": object()})


class DigestTests(unittest.TestCase):
    def test_sha256_bytes(self):
        self.assertEqual(util.sha256_bytes(b""),
                         "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
        self.assertEqual(len(util.sha256_bytes(b"abc")), 64)


class SafePathTests(unittest.TestCase):
    def test_accepts_normal_relative_paths(self):
        for p in ["a.txt", "dir/a.txt", "a/b/c.bin", "unicod\u00e9.txt"]:
            self.assertEqual(util.safe_rel_path(p), p)

    def test_rejects_traversal_and_absolute(self):
        for p in ["", ".", "..", "../evil", "a/../b", "/etc/passwd", "a//b",
                  "a/./b", "C:\\Windows", "a\\b", "nul\x00byte", "dir/"]:
            with self.assertRaises(util.BugjarError, msg=p):
                util.safe_rel_path(p)

    def test_rejects_windows_drive_and_unc(self):
        for p in ["C:/x", "\\\\server\\share", "//server/share"]:
            with self.assertRaises(util.BugjarError, msg=p):
                util.safe_rel_path(p)


class RedactionTests(unittest.TestCase):
    def test_secret_shaped_keys_are_redacted_and_listed(self):
        env = {"PATH": "/usr/bin", "API_TOKEN": "hunter2", "MY_PASSWORD": "s3cr3t",
               "LANG": "C"}
        vars_, redactions = util.redact_env(env)
        self.assertEqual(vars_["PATH"], "/usr/bin")
        self.assertNotIn("hunter2", json.dumps(vars_))
        self.assertEqual({r["key"] for r in redactions}, {"API_TOKEN", "MY_PASSWORD"})
        self.assertTrue(all(len(r["sha256"]) == 64 for r in redactions))

    def test_explicit_allow_and_redact_overrides(self):
        env = {"API_TOKEN": "abc", "BUGGY": "kept"}
        v1, r1 = util.redact_env(env, allow=["API_TOKEN"])
        self.assertEqual(v1["API_TOKEN"], "abc")
        self.assertEqual(r1, [])
        v2, r2 = util.redact_env(env, force_redact=["BUGGY"])
        self.assertNotEqual(v2["BUGGY"], "kept")
        self.assertEqual(r2[0]["key"], "BUGGY")

    def test_safe_keys_are_not_redacted(self):
        env = {"LANG": "C", "TZ": "UTC", "PYTHONHASHSEED": "0", "HOME": "/home/x"}
        _, redactions = util.redact_env(env)
        self.assertEqual(redactions, [])


class LimitTests(unittest.TestCase):
    def test_limits_are_positive_and_bounded(self):
        self.assertGreater(util.MAX_BLOB_BYTES, 0)
        self.assertGreater(util.MAX_TOTAL_BYTES, util.MAX_BLOB_BYTES)
        self.assertGreater(util.MAX_MEMBERS, 1)


if __name__ == "__main__":
    unittest.main()
