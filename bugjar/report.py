"""Read-only reports: semantic diff, evidence-linked Markdown, doctor.

Deep interface: cassette path in, structured report out. Flattening, volatile
field filtering, evidence citations and profile comparison stay behind it.
"""
from __future__ import annotations

from . import cassette, observation

VOLATILE = ("cassette_id", "created_utc", "integrity", "signature", "lineage")


def flatten(obj, prefix=""):
    if isinstance(obj, dict):
        for key in sorted(obj):
            yield from flatten(obj[key], prefix + "." + str(key) if prefix else str(key))
    elif isinstance(obj, (list, tuple)):
        for i, value in enumerate(obj):
            yield from flatten(value, "%s[%d]" % (prefix, i))
    else:
        yield prefix, obj


def diff(a, b) -> dict:
    ma, _ = cassette.load(a)
    mb, _ = cassette.load(b)
    fa = {k: v for k, v in flatten(ma) if k.split(".")[0] not in VOLATILE}
    fb = {k: v for k, v in flatten(mb) if k.split(".")[0] not in VOLATILE}
    changes = []
    for key in sorted(set(fa) | set(fb)):
        va, vb = fa.get(key, "<absent>"), fb.get(key, "<absent>")
        if va != vb:
            changes.append({"path": key, "a": va, "b": vb})
    return {"action": "diff", "a": str(a), "b": str(b),
            "cassette_a": ma.get("cassette_id"), "cassette_b": mb.get("cassette_id"),
            "change_count": len(changes), "changes": changes}


def explain(path) -> str:
    manifest, blobs = cassette.load(path)
    obs = manifest.get("observation") or {}
    caveats = manifest.get("caveats") or []
    sig = manifest.get("signature")
    lines = [
        "# Cassette %s" % manifest.get("cassette_id"),
        "",
        "Command: `%s` [evidence: command.argv]" %
        " ".join(str(x) for x in (manifest.get("command") or {}).get("argv", [])),
        "Recorded: %s [evidence: created_utc = %s]" %
        (manifest.get("created_utc"), manifest.get("created_utc")),
        "",
        "## Observation",
        "",
        "Exit code: %s [evidence: observation.exit_code = %s]" %
        (obs.get("exit_code"), obs.get("exit_code")),
        "stdout: %s bytes, sha256 %s [evidence: observation.stdout]" %
        ((obs.get("stdout") or {}).get("size"), (obs.get("stdout") or {}).get("sha256")),
        "stderr: %s bytes, sha256 %s [evidence: observation.stderr]" %
        ((obs.get("stderr") or {}).get("size"), (obs.get("stderr") or {}).get("sha256")),
        "created files: %d [evidence: observation.created has %d keys]" %
        (len(obs.get("created") or {}), len(obs.get("created") or {})),
        "modified files: %d [evidence: observation.modified has %d keys]" %
        (len(obs.get("modified") or {}), len(obs.get("modified") or {})),
        "deleted files: %d [evidence: observation.deleted has %d items]" %
        (len(obs.get("deleted") or []), len(obs.get("deleted") or [])),
        "witness: %s [evidence: observation.witness]" % obs.get("witness"),
        "",
        "## Environment",
        "",
        "variables recorded: %d [evidence: environment.vars has %d keys]" %
        (len((manifest.get("environment") or {}).get("vars") or {}),
         len((manifest.get("environment") or {}).get("vars") or {})),
        "redactions: %d [evidence: environment.redactions]" %
        len((manifest.get("environment") or {}).get("redactions") or []),
        "",
        "## Caveats",
        "",
    ]
    if caveats:
        lines += ["- %s [evidence: caveats]" % c for c in caveats]
    else:
        lines.append("- none recorded [evidence: caveats = []]")
    lines += [
        "",
        "## Integrity",
        "",
        "root: %s [evidence: integrity.root]" %
        (manifest.get("integrity") or {}).get("root"),
        "signed: %s [evidence: signature = %s]" %
        ("yes (local HMAC only)" if sig else "no", "present" if sig else "null"),
        "The network and the wall clock are outside the recorded model. "
        "[evidence: caveats and SECURITY.md]",
    ]
    lineage = manifest.get("lineage")
    if lineage:
        lines += ["", "## Lineage", "",
                  "parent: %s [evidence: lineage.parent]" % lineage.get("parent"),
                  "kept units: %d [evidence: lineage.kept_units]" %
                  len(lineage.get("kept_units") or []),
                  "oracle calls: %s [evidence: lineage.oracle_calls]" %
                  lineage.get("oracle_calls")]
    return "\n".join(lines) + "\n"


def doctor(path) -> dict:
    manifest, blobs = cassette.load(path)
    mismatches = observation.profile_mismatches(
        manifest.get("profile") or {}, observation.profile(manifest["command"]["argv"]))
    problems = cassette.verify_integrity(manifest, blobs)
    return {
        "action": "doctor", "cassette": str(path),
        "comparable": not mismatches, "mismatches": mismatches,
        "integrity": "ok" if not problems else "failed",
        "integrity_problems": problems,
        "signed": manifest.get("signature") is not None,
        "inputs": len(manifest.get("inputs") or []),
        "caveats": list(manifest.get("caveats") or []),
        "format": manifest.get("format"),
    }
