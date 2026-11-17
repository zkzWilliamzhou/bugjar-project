import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from helpers import ROOT, minimal_manifest, rewrite_zip
from bugjar import cassette, util


class CassetteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bugjar-test-")
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def path(self, name="c.bugjar"):
        return self.dir / name

    def good(self, name="c.bugjar"):
        manifest = minimal_manifest()
        blob = b"hello cassette"
        blobs = {util.sha256_bytes(blob): blob}
        cassette.save(self.path(name), manifest, blobs)
        return self.path(name)

    def test_roundtrip_and_integrity(self):
        p = self.good()
        manifest, blobs = cassette.load(p)
        self.assertEqual(manifest["format"], "bugjar/1")
        self.assertEqual(len(manifest["integrity"]["root"]), 64)
        self.assertIn(b"hello cassette", b"".join(blobs.values()))
        self.assertEqual(cassette.verify_integrity(manifest, blobs), [])

    def test_blob_name_must_equal_content_digest(self):
        p = self.good()
        bad = self.path("rename.bugjar")

        def mutate(items):
            out = []
            for name, data, attr, ctype in items:
                if name.startswith("blobs/"):
                    name = "blobs/" + "1" * 64
                out.append((name, data, attr, ctype))
            return out

        rewrite_zip(p, bad, mutate)
        with self.assertRaises(util.BugjarError):
            cassette.load(bad)

    def test_corrupt_blob_is_detected(self):
        p = self.good()
        bad = self.path("bad.bugjar")

        def mutate(items):
            out = []
            for name, data, attr, ctype in items:
                if name.startswith("blobs/"):
                    data = b"tampered"
                out.append((name, data, attr, ctype))
            return out

        rewrite_zip(p, bad, mutate)
        with self.assertRaises(util.BugjarError) as ctx:
            cassette.load(bad)
        self.assertIn("digest", str(ctx.exception).lower())

    def test_corrupt_manifest_field_is_detected(self):
        p = self.good()
        bad = self.path("bad2.bugjar")

        def mutate(items):
            out = []
            for name, data, attr, ctype in items:
                if name == "manifest.json":
                    m = json.loads(data)
                    m["command"]["argv"] = ["evil"]
                    data = util.canonical_json(m)
                out.append((name, data, attr, ctype))
            return out

        rewrite_zip(p, bad, mutate)
        with self.assertRaises(util.BugjarError):
            cassette.load(bad)

    def test_zip_slip_rejected(self):
        p = self.good()
        bad = self.path("slip.bugjar")
        rewrite_zip(p, bad, lambda items: items + [("../evil.txt", b"x", 0o644 << 16, zipfile.ZIP_DEFLATED)])
        with self.assertRaises(util.BugjarError):
            cassette.load(bad)

    def test_absolute_member_rejected(self):
        p = self.good()
        bad = self.path("abs.bugjar")
        rewrite_zip(p, bad, lambda items: items + [("/etc/passwd", b"x", 0o644 << 16, zipfile.ZIP_DEFLATED)])
        with self.assertRaises(util.BugjarError):
            cassette.load(bad)

    def test_symlink_member_rejected(self):
        p = self.good()
        bad = self.path("link.bugjar")
        rewrite_zip(p, bad, lambda items: items + [("blobs/link", b"target", (0o120777 << 16), zipfile.ZIP_DEFLATED)])
        with self.assertRaises(util.BugjarError):
            cassette.load(bad)

    def test_duplicate_member_rejected(self):
        p = self.good()
        bad = self.path("dup.bugjar")
        rewrite_zip(p, bad, lambda items: items + [("manifest.json", b"{}", 0o644 << 16, zipfile.ZIP_DEFLATED)])
        with self.assertRaises(util.BugjarError):
            cassette.load(bad)

    def test_oversized_blob_rejected(self):
        p = self.good()
        bad = self.path("big.bugjar")
        rewrite_zip(p, bad, lambda items: items + [("blobs/" + "0" * 64, b"x" * (util.MAX_BLOB_BYTES + 1), 0o644 << 16, zipfile.ZIP_STORED)])
        with self.assertRaises(util.BugjarError):
            cassette.load(bad)

    def test_truncated_file_rejected(self):
        p = self.good()
        bad = self.path("trunc.bugjar")
        bad.write_bytes(p.read_bytes()[:40])
        with self.assertRaises(util.BugjarError):
            cassette.load(bad)

    def test_bad_format_rejected(self):
        p = self.good()
        bad = self.path("fmt.bugjar")

        def mutate(items):
            out = []
            for name, data, attr, ctype in items:
                if name == "manifest.json":
                    m = json.loads(data)
                    m["format"] = "bugjar/999"
                    data = util.canonical_json(m)
                out.append((name, data, attr, ctype))
            return out

        rewrite_zip(p, bad, mutate)
        # root now mismatches too; either reason is acceptable, but it must be refused
        with self.assertRaises(util.BugjarError):
            cassette.load(bad)

    def test_hmac_signature_roundtrip_and_tamper(self):
        key = b"a-local-shared-key"
        manifest = minimal_manifest()
        blob = b"signed"
        blobs = {util.sha256_bytes(blob): blob}
        cassette.save(self.path("signed.bugjar"), manifest, blobs, sign_key=key)
        m, b = cassette.load(self.path("signed.bugjar"), key=key)
        self.assertIsNotNone(m["signature"])
        self.assertEqual(cassette.verify_integrity(m, b, key=key), [])
        with self.assertRaises(util.BugjarError):
            cassette.load(self.path("signed.bugjar"), key=b"wrong-key")

    def test_unsigned_cassette_is_labelled(self):
        p = self.good()
        m, _ = cassette.load(p)
        self.assertIsNone(m["signature"])


if __name__ == "__main__":
    unittest.main()
