"""Observation semantics: seven channels, profiles, and manifest construction.

Deep interface: callers hand over an ExecResult and an input-world digest map;
this module owns normalization, comparison, and the cassette document shape.
"""
from __future__ import annotations

import copy
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from . import util

CHANNELS = ("exit_code", "stdout", "stderr", "created", "modified", "deleted", "witness")
DEFAULT_SIGNATURE = ("exit_code", "stderr", "stdout")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    return util.sha256_bytes(os.urandom(32))[:16]


def observe(result, before: Dict[str, str]) -> dict:
    stdout = util.normalize_text(result.stdout, str(result.sandbox))
    stderr = util.normalize_text(result.stderr, str(result.sandbox))
    created = {p: d for p, d in result.after.items() if p not in before}
    modified = {p: d for p, d in result.after.items()
                if p in before and before[p] != d}
    deleted = sorted(p for p in before if p not in result.after)
    return {
        "exit_code": result.exit_code,
        "stdout": {"sha256": util.sha256_bytes(stdout), "size": len(stdout),
                   "preview": util.preview(stdout)},
        "stderr": {"sha256": util.sha256_bytes(stderr), "size": len(stderr),
                   "preview": util.preview(stderr)},
        "created": created,
        "modified": modified,
        "deleted": deleted,
        "witness": util.witness(result.argv, result.env, result.stdin_sha256, before),
    }


def profile(argv: List[str]) -> dict:
    """Fingerprint argv[0] as an absolute path, never relative to the caller's cwd."""
    exe = str(argv[0]) if argv else ""
    resolved = exe
    if exe and not os.path.isabs(exe):
        import shutil
        found = shutil.which(exe)
        resolved = os.path.realpath(found) if found else exe
    digest = "0" * 64
    try:
        p = Path(resolved)
        if p.is_file() and os.path.isabs(str(p)):
            digest = util.sha256_bytes(p.read_bytes()[:util.MAX_BLOB_BYTES])
    except OSError:
        pass
    return {
        "os": platform.system(),
        "machine": platform.machine(),
        "python": "%d.%d" % sys.version_info[:2],
        "executable": resolved,
        "executable_sha256": digest,
        "locale": "C",
        "limits_available": (os.name == "posix" and not sys.platform.startswith("win")),
        "normalization": dict(util.NORMALIZATION),
    }


def profile_mismatches(recorded: dict, current: dict) -> List[str]:
    out = []
    for key in ("os", "machine", "python", "executable", "executable_sha256",
                "locale", "limits_available"):
        if recorded.get(key) != current.get(key):
            out.append("%s: recorded=%r current=%r" %
                       (key, recorded.get(key), current.get(key)))
    return out


def build_manifest(argv, env_vars, redactions, stdin_sha256, before,
                   observation, caveats, timeout, repeat, lineage=None) -> dict:
    doc = {
        "format": util.FORMAT,
        "cassette_id": new_id(),
        "created_utc": now(),
        "command": {"argv": list(argv), "timeout_s": float(timeout),
                    "repeat": int(repeat)},
        "profile": profile(argv),
        "environment": {"vars": dict(env_vars), "redactions": list(redactions)},
        "stdin_sha256": stdin_sha256,
        "inputs": [{"path": p, "sha256": d, "size": 0, "mode": "600"}
                   for p, d in sorted(before.items())],
        "observation": copy.deepcopy(observation),
        "caveats": list(caveats),
        "integrity": {"algorithm": "sha256", "root": "", "members": {}},
        "signature": None,
    }
    if lineage is not None:
        doc["lineage"] = lineage
    return doc


def channels(recorded: dict, observed: dict) -> Dict[str, dict]:
    out = {}
    for name in CHANNELS:
        a, b = recorded.get(name), observed.get(name)
        if isinstance(a, dict) and isinstance(b, dict):
            match = util.canonical_json(a) == util.canonical_json(b)
        else:
            match = a == b
        out[name] = {"match": bool(match), "recorded": a, "observed": b}
    return out


def same(a: dict, b: dict) -> bool:
    return util.canonical_json(a) == util.canonical_json(b)


def signature_match(recorded: dict, observed: dict, signature) -> bool:
    for name in signature:
        a, b = recorded.get(name), observed.get(name)
        if isinstance(a, dict) and isinstance(b, dict):
            if util.canonical_json(a) != util.canonical_json(b):
                return False
        elif a != b:
            return False
    return True
