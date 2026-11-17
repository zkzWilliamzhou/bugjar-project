"""Freeze observable CLI behavior. Output is scrubbed of volatile fields.

Usage: python3 tools/golden.py <output.txt>
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.helpers import controlled_env, build_world  # noqa: E402


def scrub(text, tmp):
    text = text.replace(str(tmp), "<TMP>")
    text = text.replace(str(tmp).replace("\\", "/"), "<TMP>")
    text = re.sub(r'(?<![0-9a-f])[0-9a-f]{16}(?![0-9a-f])', '<ID16>', text)
    text = re.sub(r'"cassette_id": "[^"]+"', '"cassette_id": "<ID>"', text)
    text = re.sub(r'"created_utc": "[^"]+"', '"created_utc": "<TS>"', text)
    text = re.sub(r'"root": "[0-9a-f]{64}"', '"root": "<ROOT>"', text)
    text = re.sub(r'root: [0-9a-f]{64}', 'root: <ROOT>', text)
    text = re.sub(r'"value": "[0-9a-f]{64}"', '"value": "<HMAC>"', text)
    text = re.sub(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', '<TS>', text)
    text = re.sub(r'/[^\s"\'<>]*bugjar-(?:world|golden)-[A-Za-z0-9_]+', '<TMP>', text)
    return text


def main():
    out_file = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    tmp = tempfile.TemporaryDirectory(prefix="bugjar-golden-")
    root = Path(tmp.name)
    env = controlled_env()
    env["PYTHONPATH"] = str(ROOT)
    env["BUGJAR_GOLDEN_SECRET"] = "do-not-leak-abc123"
    lines = []
    fixtures = {
        "worldA": "hello",
        "worldB": "world",
        "boom": "BOOM",
    }
    for name, data in fixtures.items():
        build_world(root / name, data=data)
    (root / "key.bin").write_bytes(b"golden-shared-key-0123456789")
    (root / "wrong.bin").write_bytes(b"definitely-not-the-key-0000")
    (root / "stdin.txt").write_text("hello from stdin\n", encoding="utf-8")

    def case(label, args):
        proc = subprocess.run([sys.executable, "-m", "bugjar"] + args,
                              cwd=str(root), env=env, capture_output=True,
                              text=True, timeout=180)
        lines.append("### %s :: %s" % (label, " ".join(args)))
        lines.append("rc=%d" % proc.returncode)
        lines.append("STDOUT<<")
        lines.append(scrub(proc.stdout, root).rstrip("\n"))
        lines.append(">>")
        lines.append("STDERR<<")
        lines.append(scrub(proc.stderr, root).rstrip("\n"))
        lines.append(">>")

    cmd = [sys.executable, "probe.py"]
    case("01 version", ["version"])
    case("02 run A", ["run", "--root", "worldA", "--out", "a.bugjar", "--json", "--"] + cmd)
    case("03 verify A", ["verify", "a.bugjar", "--json"])
    case("04 verify A repeat2", ["verify", "a.bugjar", "--json", "--repeat", "2"])
    case("05 doctor A", ["doctor", "a.bugjar", "--json"])
    case("06 explain A", ["explain", "a.bugjar"])
    case("07 shrink A", ["shrink", "a.bugjar", "--out", "a.min.bugjar", "--budget", "120", "--json"])
    case("08 verify A.min", ["verify", "a.min.bugjar", "--json"])
    case("09 explain A.min", ["explain", "a.min.bugjar"])
    case("10 doctor A.min", ["doctor", "a.min.bugjar", "--json"])
    case("11 run B", ["run", "--root", "worldB", "--out", "b.bugjar", "--json", "--"] + cmd)
    case("12 diff A B", ["diff", "a.bugjar", "b.bugjar", "--json"])
    case("13 diff A A", ["diff", "a.bugjar", "a.bugjar", "--json"])
    case("14 explain B", ["explain", "b.bugjar"])
    case("15 run boom", ["run", "--root", "boom", "--out", "boom.bugjar", "--json", "--"] + cmd)
    case("16 verify boom", ["verify", "boom.bugjar", "--json"])
    case("17 shrink boom", ["shrink", "boom.bugjar", "--out", "boom.min.bugjar", "--budget", "120", "--json"])
    case("18 verify boom.min", ["verify", "boom.min.bugjar", "--json"])
    case("19 run signed", ["run", "--root", "worldA", "--out", "s.bugjar", "--json", "--sign", "key.bin", "--"] + cmd)
    case("20 verify signed good key", ["verify", "s.bugjar", "--json", "--key", "key.bin"])
    case("21 verify signed bad key", ["verify", "s.bugjar", "--json", "--key", "wrong.bin"])
    case("22 doctor signed no key", ["doctor", "s.bugjar", "--json"])
    case("23 run with secret env", ["run", "--root", "worldA", "--out", "sec.bugjar", "--json", "--env", "BUGJAR_GOLDEN_SECRET", "--"] + cmd)
    case("24 verify secret env", ["verify", "sec.bugjar", "--json"])
    case("25 verify secret env allowed", ["verify", "sec.bugjar", "--json", "--allow-redacted"])
    case("26 run with stdin", ["run", "--root", "worldA", "--stdin", "stdin.txt", "--out", "stdin.bugjar", "--json", "--"] + cmd)
    case("27 verify stdin", ["verify", "stdin.bugjar", "--json"])
    case("28 shrink budget1", ["shrink", "a.bugjar", "--out", "never.bugjar", "--budget", "1", "--json"])
    case("29 run missing command", ["run", "--root", "worldA", "--out", "x.bugjar", "--json", "--"])
    case("30 verify nonexistent", ["verify", "nope.bugjar", "--json"])

    # Deterministic corruption. A raw byte flip lands at a layout-dependent
    # offset because created_utc changes the zip, so the harness uses a
    # semantic mutation and a truncation instead.
    from tests.helpers import rewrite_zip  # noqa: E402
    rewrite_zip(root / "a.bugjar", root / "corrupt.bugjar", lambda items: [
        (n, b"{broken manifest" if n == "manifest.json" else d, a, c)
        for n, d, a, c in items])
    (root / "trunc.bugjar").write_bytes((root / "a.bugjar").read_bytes()[:64])
    case("31 verify corrupt", ["verify", "corrupt.bugjar", "--json"])
    case("32 explain corrupt", ["explain", "corrupt.bugjar"])
    case("33 verify truncated", ["verify", "trunc.bugjar", "--json"])
    case("34 doctor truncated", ["doctor", "trunc.bugjar", "--json"])

    text = "\n".join(lines).rstrip() + "\n"
    if out_file:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(text, encoding="utf-8")
        print("wrote %d lines to %s" % (len(lines), out_file))
    else:
        sys.stdout.write(text)
    tmp.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
