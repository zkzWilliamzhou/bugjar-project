"""Generate hostile cassettes and assert every one is refused. No pytest needed."""
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bugjar import cassette, util  # noqa: E402
from tests.helpers import minimal_manifest, rewrite_zip  # noqa: E402


def build_valid(path):
    blob = b"adversarial payload"
    cassette.save(path, minimal_manifest(), {util.sha256_bytes(blob): blob})
    return path


def attacks():
    yield "zip_slip_dotdot", lambda items: items + [("../evil", b"x", 0o644 << 16, zipfile.ZIP_DEFLATED)]
    yield "zip_slip_nested", lambda items: items + [("a/../../evil", b"x", 0o644 << 16, zipfile.ZIP_DEFLATED)]
    yield "absolute_posix", lambda items: items + [("/etc/passwd", b"x", 0o644 << 16, zipfile.ZIP_DEFLATED)]
    yield "absolute_windows", lambda items: items + [("C:/Windows/x", b"x", 0o644 << 16, zipfile.ZIP_DEFLATED)]
    yield "unc_path", lambda items: items + [("//server/share", b"x", 0o644 << 16, zipfile.ZIP_DEFLATED)]
    yield "backslash", lambda items: items + [("a\\b\\c", b"x", 0o644 << 16, zipfile.ZIP_DEFLATED)]
    yield "nul_byte", lambda items: items + [("a\x00b", b"x", 0o644 << 16, zipfile.ZIP_DEFLATED)]
    yield "symlink_member", lambda items: items + [("blobs/link", b"x", 0o120777 << 16, zipfile.ZIP_DEFLATED)]
    yield "device_member", lambda items: items + [("blobs/dev", b"x", 0o20666 << 16, zipfile.ZIP_DEFLATED)]
    yield "duplicate_manifest", lambda items: items + [("manifest.json", b"{}", 0o644 << 16, zipfile.ZIP_DEFLATED)]
    yield "unexpected_member", lambda items: items + [("payload.bin", b"x", 0o644 << 16, zipfile.ZIP_DEFLATED)]
    yield "blob_bad_name", lambda items: items + [("blobs/not-a-digest", b"x", 0o644 << 16, zipfile.ZIP_DEFLATED)]
    yield "oversized_blob", lambda items: items + [("blobs/" + "0" * 64, b"x" * (util.MAX_BLOB_BYTES + 1), 0o644 << 16, zipfile.ZIP_STORED)]
    yield "oversized_manifest", lambda items: [(n, b"x" * (util.MAX_BLOB_BYTES + 1) if n == "manifest.json" else d, a, c) for n, d, a, c in items]
    yield "manifest_not_object", lambda items: [(n, b"[1,2,3]" if n == "manifest.json" else d, a, c) for n, d, a, c in items]
    yield "manifest_bad_json", lambda items: [(n, b"{not json" if n == "manifest.json" else d, a, c) for n, d, a, c in items]
    yield "wrong_blob_digest", lambda items: [(n, b"tampered" if n.startswith("blobs/") else d, a, c) for n, d, a, c in items]
    yield "renamed_blob", lambda items: [("blobs/" + "1" * 64 if n.startswith("blobs/") else n, d, a, c) for n, d, a, c in items]
    yield "unlisted_blob", lambda items: items + [("blobs/" + "2" * 64, b"x", 0o644 << 16, zipfile.ZIP_DEFLATED)]
    yield "missing_manifest", lambda items: [x for x in items if x[0] != "manifest.json"]
    yield "truncated_blob", lambda items: [(n, d[:2] if n.startswith("blobs/") else d, a, c) for n, d, a, c in items]


def encrypted_attack(src, dst):
    """Patch the general-purpose bit 0 in local and central headers.

    Setting ZipInfo.flag_bits before writestr does not work: zipfile resets it.
    Byte-patching the produced archive is the only way to create a cassette
    that actually carries the encrypted flag.
    """
    import struct
    raw = bytearray(Path(src).read_bytes())
    idx = 0
    patched = 0
    while True:
        idx = raw.find(b"PK\x03\x04", idx)
        if idx < 0:
            break
        val = struct.unpack_from("<H", raw, idx + 6)[0]
        struct.pack_into("<H", raw, idx + 6, val | 1)
        patched += 1
        idx += 4
    idx = 0
    while True:
        idx = raw.find(b"PK\x01\x02", idx)
        if idx < 0:
            break
        val = struct.unpack_from("<H", raw, idx + 8)[0]
        struct.pack_into("<H", raw, idx + 8, val | 1)
        idx += 4
    assert patched > 0, "failed to patch local headers"
    Path(dst).write_bytes(bytes(raw))
    return dst


def directory_member_attack(src, dst):
    return rewrite_zip(src, dst, lambda items: items + [
        ("blobs/" + "3" * 64, b"", 0o40755 << 16, zipfile.ZIP_STORED)])


def main():
    tmp = tempfile.TemporaryDirectory(prefix="bugjar-adv-")
    root = Path(tmp.name)
    valid = build_valid(root / "valid.bugjar")
    failures = []
    passed = 0
    for name, mutate in attacks():
        out = root / (name + ".bugjar")
        try:
            rewrite_zip(valid, out, mutate)
            cassette.load(out)
        except util.BugjarError:
            passed += 1
        except Exception as exc:
            failures.append("%s: escaped as %s: %s" % (name, type(exc).__name__, exc))
        else:
            failures.append("%s: ACCEPTED a hostile cassette" % name)
    for name, fn in (("encrypted_member", encrypted_attack),
                     ("directory_member", directory_member_attack)):
        out = root / (name + ".bugjar")
        try:
            fn(valid, out)
            cassette.load(out)
        except util.BugjarError:
            passed += 1
        except Exception as exc:
            failures.append("%s: escaped as %s: %s" % (name, type(exc).__name__, exc))
        else:
            failures.append("%s: ACCEPTED a hostile cassette" % name)
    print("adversarial: %d/%d hostile cassettes refused" %
          (passed, passed + len(failures)))
    for f in failures:
        print("  FAIL " + f)
    tmp.cleanup()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
