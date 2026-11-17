"""Shared fixtures. Standard library only; no pytest dependency."""
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURE = '''\
import pathlib, sys
p = pathlib.Path("data.txt")
if not p.exists():
    sys.stderr.write("missing data\\n")
    sys.exit(2)
text = p.read_text()
if "BOOM" in text:
    sys.stderr.write("boom detected\\n")
    sys.exit(3)
out = text.strip().upper()
pathlib.Path("result.txt").write_text(out)
sys.stdout.write(out + "\\n")
'''

EXTERNAL_FIXTURE = '''\
import os, pathlib
p = pathlib.Path(os.environ.get("BUGJAR_EXTERNAL", "missing"))
sys.stdout.write(p.read_text() if p.exists() else "empty")
'''


def build_world(root, data="hello", noise=8, script=FIXTURE):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "probe.py").write_text(script, encoding="utf-8")
    (root / "data.txt").write_text(data, encoding="utf-8")
    for i in range(noise):
        (root / ("noise_%d.txt" % i)).write_text("x" * (i + 1), encoding="utf-8")
    return root


def argv():
    return [sys.executable, "probe.py"]


def minimal_manifest():
    return {
        "format": "bugjar/1",
        "cassette_id": "0" * 16,
        "created_utc": "1970-01-01T00:00:00Z",
        "command": {"argv": ["true"], "timeout_s": 5.0, "repeat": 1},
        "profile": {"os": "Linux", "machine": "x86_64", "python": "3.10",
                    "executable": "/bin/true", "executable_sha256": "0" * 64,
                    "locale": "C", "limits_available": True, "normalization": {}},
        "environment": {"vars": {}, "redactions": []},
        "stdin_sha256": "0" * 64,
        "inputs": [],
        "observation": {"exit_code": 0, "stdout": {"sha256": "0" * 64, "size": 0, "preview": ""},
                        "stderr": {"sha256": "0" * 64, "size": 0, "preview": ""},
                        "created": {}, "modified": {}, "deleted": [], "witness": "0" * 64},
        "caveats": [],
        "integrity": {"algorithm": "sha256", "root": "", "members": {}},
        "signature": None,
    }


def resign(path, mutate):
    """Load a valid cassette, mutate its manifest, recompute the integrity root."""
    from bugjar import cassette
    manifest, blobs = cassette.load(path)
    mutate(manifest)
    cassette.save(path, manifest, blobs)
    return path


def controlled_env(extra=None):
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
        "PYTHONHASHSEED": "0",
        "PYTHONIOENCODING": "utf-8",
        "SOURCE_DATE_EPOCH": "1700000000",
    }
    if os.name == "nt":
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")
    if extra:
        env.update(extra)
    return env


def rewrite_zip(src, dst, mutate):
    """Rebuild a cassette zip, letting a test mutate member names/bytes/attrs."""
    with zipfile.ZipFile(src) as zin:
        items = [(i.filename, zin.read(i.filename), i.external_attr, i.compress_type)
                 for i in zin.infolist()]
    items = mutate(items)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data, attr, ctype in items:
            info = zipfile.ZipInfo(name)
            info.external_attr = attr
            info.compress_type = ctype
            zout.writestr(info, data)
    return dst
