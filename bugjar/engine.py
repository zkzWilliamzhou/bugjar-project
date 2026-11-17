"""Orchestration: run, verify and shrink.

Structure-only refactor of the frozen v1 behavior. Sandbox mechanics live in
runner, channel semantics in observation, reduction in minimizer, and read-only
reports in report. The public API of this module is unchanged.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

from . import cassette, minimizer, observation, report, runner, util

CHANNELS = observation.CHANNELS
DEFAULT_SIGNATURE = observation.DEFAULT_SIGNATURE
BudgetExhausted = minimizer.BudgetExhausted

# Read-only reports are part of the public engine surface.
diff = report.diff
explain = report.explain
doctor = report.doctor

# Compatibility aliases used by the review probes in REVIEW_LOG.md.
_ddmin = minimizer.ddmin
_profile = observation.profile
_snapshot = runner.snapshot


def run(root, argv, out, env_base, timeout=10.0, stdin_bytes=b"",
        env_allow=(), env_redact=(), sign_key=None, repeat=1) -> dict:
    """Record one command into a cassette and return a JSON-able summary."""
    if not argv:
        raise util.BugjarError("empty command: pass a command after --")
    root = Path(root).resolve()
    if not root.is_dir():
        raise util.BugjarError("--root is not a directory: %s" % root)
    env_vars, redactions = util.prepare_env(env_base, allow=env_allow,
                                            force_redact=env_redact)
    before, caveats = runner.snapshot(root)
    result = runner.execute(root, list(argv), env_vars, float(timeout), stdin_bytes)
    try:
        if result.timed_out:
            raise util.BugjarError("capture timed out after %.2fs" % timeout)
        obs = observation.observe(result, before)
        for c in result.caveats:
            if c not in caveats:
                caveats.append(c)
        doc = observation.build_manifest(argv, env_vars, redactions,
                                         result.stdin_sha256, before, obs,
                                         caveats, timeout, repeat)
        cassette.save(out, doc, result.blobs, sign_key=sign_key)
        return {
            "action": "run",
            "out": str(out),
            "cassette_id": doc["cassette_id"],
            "inputs": len(before),
            "redactions": len(redactions),
            "caveats": len(caveats),
            "signed": sign_key is not None,
            "observation": {
                "exit_code": obs["exit_code"],
                "created": len(obs["created"]),
                "modified": len(obs["modified"]),
                "deleted": len(obs["deleted"]),
                "stdout_bytes": obs["stdout"]["size"],
                "stderr_bytes": obs["stderr"]["size"],
            },
        }
    finally:
        runner.cleanup(result)


def verify(path, repeat=1, timeout=None, key=None, allow_redacted=False) -> dict:
    """Strict three-valued verdict. Never collapse 'cannot check' into success."""
    result = {
        "action": "verify", "cassette": str(path), "verdict": "UNVERIFIABLE",
        "integrity": "failed", "profile": "unknown", "repeats": int(repeat),
        "channels": {}, "reasons": [], "caveats": [],
    }
    try:
        manifest, blobs = cassette.load(path, key=key)
    except util.BugjarError as exc:
        result["reasons"].append("cassette load failed: %s" % exc)
        return result
    except Exception as exc:  # never let a malformed cassette escape as a crash
        result["reasons"].append("cassette load raised %s: %s" %
                                 (type(exc).__name__, exc))
        return result
    result["integrity"] = "ok"
    result["caveats"] = list(manifest.get("caveats") or [])

    mismatches = observation.profile_mismatches(
        manifest.get("profile") or {}, observation.profile(manifest["command"]["argv"]))
    if mismatches:
        result["profile"] = "incomparable"
        result["reasons"].extend("profile mismatch: " + m for m in mismatches)
        return result
    result["profile"] = "comparable"
    if (manifest.get("profile") or {}).get("executable_sha256", "0" * 64) == "0" * 64:
        result["reasons"].append(
            "toolchain fingerprint incomplete: argv[0] could not be resolved to an "
            "absolute executable; replay cannot be verified")
        return result

    redactions = (manifest.get("environment") or {}).get("redactions") or []
    if redactions:
        if not allow_redacted:
            result["reasons"].append(
                "%d environment value(s) were redacted at capture; replay cannot be faithful. "
                "Use --allow-redacted to accept a weakened verdict." % len(redactions))
            return result
        result["caveats"].append(
            "redacted variables were allowed: replay is not faithful to the original world")

    effective_timeout = float(timeout if timeout is not None
                              else manifest["command"]["timeout_s"])
    argv = list(manifest["command"]["argv"])
    env = dict((manifest.get("environment") or {}).get("vars") or {})
    stdin_digest = manifest.get("stdin_sha256", util.sha256_bytes(b""))
    stdin = blobs.get(cassette.BLOB_PREFIX + stdin_digest, b"")
    recorded = manifest.get("observation") or {}

    observations = []
    timeout_reason = None
    for _ in range(max(1, int(repeat))):
        dst = runner.sandbox()
        try:
            before = runner.restore(manifest, blobs, dst)
            expected = {i["path"]: i["sha256"] for i in manifest.get("inputs", [])}
            if before != expected:
                result["reasons"].append("input reconstruction mismatch")
                return result
            res = runner.execute(dst, argv, env, effective_timeout, stdin)
            try:
                if res.timed_out:
                    timeout_reason = "replay timeout after %.2fs" % effective_timeout
                    observations = []
                    break
                observations.append(observation.observe(res, before))
            finally:
                runner.cleanup(res)
        except util.BugjarError as exc:
            result["reasons"].append("replay failed: %s" % exc)
            return result
        finally:
            runner.discard(dst)
    if timeout_reason:
        result["reasons"].append(timeout_reason)
        return result
    if not observations:
        result["reasons"].append("no replay completed")
        return result
    if len(observations) > 1 and any(not observation.same(observations[0], o)
                                     for o in observations[1:]):
        result["reasons"].append(
            "nondeterminism: repeated replays disagree; no majority vote is taken")
        return result
    first = observations[0]
    result["channels"] = observation.channels(recorded, first)
    mismatched = [c for c, v in result["channels"].items() if not v["match"]]
    if mismatched:
        result["verdict"] = "DIVERGED"
        result["reasons"].append("differing channels: " + ", ".join(sorted(mismatched)))
    else:
        result["verdict"] = "REPRODUCED"
    if redactions and allow_redacted:
        result["caveats"].append("verdict is weakened by --allow-redacted")
    return result


def shrink(src, out, budget=200, signature=DEFAULT_SIGNATURE, timeout=None,
           allow_redacted=False, sign_key=None, allow_empty_world=False) -> dict:
    """Delta-debug a recorded World down to the units that keep a failure signature."""
    manifest, blobs = cassette.load(src)
    if not manifest.get("observation"):
        raise util.BugjarError("cassette has no observation to shrink against")
    redactions = (manifest.get("environment") or {}).get("redactions") or []
    if redactions and not allow_redacted:
        return {"action": "shrink", "verdict": "UNVERIFIABLE",
                "reason": "parent has redacted environment values; pass --allow-redacted",
                "oracle_calls": 0}
    sig = tuple(signature)
    for name in sig:
        if name not in CHANNELS:
            raise util.BugjarError("unknown failure signature channel: %s" % name)
    if not sig:
        raise util.BugjarError("empty failure signature")

    file_units = [str(i["path"]) for i in manifest.get("inputs", [])]
    env_units = ["env:" + k for k in sorted(
        ((manifest.get("environment") or {}).get("vars") or {}).keys())]
    units = sorted(set(file_units)) + sorted(env_units)
    target = dict(manifest.get("observation") or {})
    argv = list(manifest["command"]["argv"])
    stored_env = dict((manifest.get("environment") or {}).get("vars") or {})
    stdin_digest = manifest.get("stdin_sha256", util.sha256_bytes(b""))
    stdin = blobs.get(cassette.BLOB_PREFIX + stdin_digest, b"")
    effective_timeout = float(timeout if timeout is not None
                              else manifest["command"]["timeout_s"])
    calls = 0
    budget = int(budget)

    def candidate(subset):
        file_set = [u for u in subset if not u.startswith("env:")]
        env_set = {u[4:] for u in subset if u.startswith("env:")}
        base = {k: v for k, v in stored_env.items() if k in env_set}
        env = dict(base)
        env.update(util.NORMALIZATION)
        dst = runner.sandbox()
        try:
            before = {}
            for rel in file_set:
                rel = util.safe_rel_path(rel)
                entry = next((i for i in manifest.get("inputs", [])
                              if i["path"] == rel), None)
                if entry is None:
                    continue
                data = blobs.get(cassette.BLOB_PREFIX + str(entry["sha256"]))
                if data is None:
                    continue
                target_path = dst / rel
                target_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                target_path.write_bytes(data)
                os.chmod(target_path, 0o600)
                before[rel] = util.sha256_bytes(data)
            res = runner.execute(dst, argv, env, effective_timeout, stdin)
            try:
                if res.timed_out:
                    return False
                observed = observation.observe(res, before)
                return observation.signature_match(target, observed, sig)
            finally:
                runner.cleanup(res)
        finally:
            runner.discard(dst)

    def oracle(subset):
        nonlocal calls
        calls += 1
        if calls > budget:
            raise minimizer.BudgetExhausted()
        # A candidate with no input files can "reproduce" a trivial
        # interpreter error. Refuse that unless the operator opts in.
        if not allow_empty_world and file_units and not any(
                not u.startswith("env:") for u in subset):
            return False
        return candidate(subset)

    try:
        current = minimizer.ddmin(units, oracle)
        if not oracle(current):
            return {"action": "shrink", "verdict": "ORACLE_UNSTABLE",
                    "reason": "final candidate did not preserve the failure signature",
                    "oracle_calls": calls}
    except minimizer.BudgetExhausted:
        return {"action": "shrink", "verdict": "BUDGET_EXHAUSTED",
                "reason": "replay budget exhausted before 1-minimality",
                "oracle_calls": calls, "budget": budget, "out": str(out)}

    kept = sorted(current)
    removed = sorted(set(units) - set(kept))
    file_set = [u for u in kept if not u.startswith("env:")]
    env_set = {u[4:] for u in kept if u.startswith("env:")}
    final_env = {k: v for k, v in stored_env.items() if k in env_set}
    final_env.update(util.NORMALIZATION)
    final_world = runner.sandbox()
    try:
        before = {}
        for rel in file_set:
            entry = next((i for i in manifest.get("inputs", [])
                          if i["path"] == rel), None)
            if entry is None:
                continue
            data = blobs.get(cassette.BLOB_PREFIX + str(entry["sha256"]))
            if data is None:
                raise util.BugjarError("missing blob for %s" % rel)
            p = final_world / rel
            p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            p.write_bytes(data)
            os.chmod(p, 0o600)
            before[rel] = util.sha256_bytes(data)
        res = runner.execute(final_world, argv, final_env, effective_timeout, stdin)
        try:
            if res.timed_out:
                return {"action": "shrink", "verdict": "TIMEOUT",
                        "reason": "final capture timed out", "oracle_calls": calls}
            obs = observation.observe(res, before)
            caveats = list(manifest.get("caveats") or [])
            for c in res.caveats:
                if c not in caveats:
                    caveats.append(c)
            if not file_set:
                caveats.append("minimization reached an empty input world; "
                               "the reproducer may be a trivial interpreter error")
            if manifest.get("signature") is not None and sign_key is None:
                caveats.append("parent was signed; minimal cassette is unsigned "
                               "because no signing key was supplied")
            lineage = {
                "parent": manifest.get("cassette_id"),
                "parent_observation": copy.deepcopy(target),
                "signature_channels": list(sig),
                "kept_units": kept,
                "removed_units": removed,
                "oracle_calls": calls,
                "budget": budget,
                "reduction": "ddmin over recorded World units",
            }
            doc = observation.build_manifest(argv, final_env, [], res.stdin_sha256,
                                             before, obs, caveats,
                                             effective_timeout, 1, lineage=lineage)
            cassette.save(out, doc, res.blobs, sign_key=sign_key)
        finally:
            runner.cleanup(res)
    finally:
        runner.discard(final_world)

    check = verify(out, repeat=1, timeout=effective_timeout,
                   key=sign_key, allow_redacted=False)
    return {
        "action": "shrink",
        "verdict": "SHRUNK" if check["verdict"] == "REPRODUCED" else "NOT_REVERIFIED",
        "parent_units": len(units),
        "kept_units": kept,
        "removed_units": removed,
        "oracle_calls": calls,
        "budget": budget,
        "signature_channels": list(sig),
        "reverified": check["verdict"] == "REPRODUCED",
        "verification": check["verdict"],
        "out": str(out),
    }
