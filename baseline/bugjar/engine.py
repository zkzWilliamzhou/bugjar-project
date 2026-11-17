"""Capture, replay, verify, shrink and explain. Standard library only."""
from __future__ import annotations

import copy
import os
import platform
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from . import cassette, util

CHANNELS = ("exit_code", "stdout", "stderr", "created", "modified", "deleted", "witness")
DEFAULT_SIGNATURE = ("exit_code", "stderr", "stdout")


class BudgetExhausted(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id() -> str:
    return util.sha256_bytes(os.urandom(32))[:16]


def _limits(timeout: float):
    def apply():
        try:
            import resource
            cpu = max(2, int(timeout) + 5)
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 5))
            resource.setrlimit(resource.RLIMIT_FSIZE,
                              (util.MAX_BLOB_BYTES, util.MAX_BLOB_BYTES))
            resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except (ImportError, OSError, ValueError):
            pass
    return apply if os.name == "posix" else None


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass


def _snapshot(root: Path) -> Tuple[Dict[str, str], List[str]]:
    """Digest every regular file below root. Symlinks are skipped and reported."""
    out: Dict[str, str] = {}
    caveats: List[str] = []
    total = 0
    for dirpath, dirnames, filenames in os.walk(str(root)):
        dirnames[:] = sorted(d for d in dirnames
                             if not os.path.islink(os.path.join(dirpath, d)))
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, str(root)).replace(os.sep, "/")
            if os.path.islink(full):
                caveats.append("skipped symlink %s: symlink worlds are not recorded" % rel)
                continue
            try:
                rel = util.safe_rel_path(rel)
            except util.BugjarError:
                caveats.append("skipped unsupported path %s" % rel)
                continue
            data = Path(full).read_bytes()
            total += len(data)
            util.validate_limits(total, len(data), len(out) + 1)
            out[rel] = util.sha256_bytes(data)
    return out, caveats


def _copy_world(root: Path, dst: Path) -> List[str]:
    caveats: List[str] = []
    total = 0
    for rel, digest in sorted(_snapshot(root)[0].items()):
        src = root / rel
        data = src.read_bytes()
        total += len(data)
        util.validate_limits(total, len(data), 0)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_bytes(data)
        os.chmod(target, 0o600)
    for rel in _snapshot(root)[1]:
        caveats.append(rel)
    return caveats


def _restore(manifest: dict, blobs: Dict[str, bytes], dst: Path) -> Dict[str, str]:
    """Rebuild the recorded world from content-addressed blobs. No extractall."""
    before: Dict[str, str] = {}
    total = 0
    for entry in manifest.get("inputs", []):
        rel = util.safe_rel_path(str(entry["path"]))
        digest = str(entry["sha256"])
        data = blobs.get(cassette.BLOB_PREFIX + digest)
        if data is None:
            raise util.BugjarError("missing blob for input %s" % rel)
        total += len(data)
        util.validate_limits(total, len(data), len(before) + 1)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_bytes(data)
        os.chmod(target, 0o600)
        before[rel] = util.sha256_bytes(data)
    return before


class ExecResult:
    def __init__(self, sandbox, argv, env, stdin_sha256, before, after,
                 exit_code, stdout, stderr, timed_out, blobs, caveats):
        self.sandbox = sandbox
        self.argv = argv
        self.env = env
        self.stdin_sha256 = stdin_sha256
        self.before = before
        self.after = after
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out
        self.blobs = blobs
        self.caveats = caveats


def _sandbox() -> Path:
    path = Path(tempfile.mkdtemp(prefix="bugjar-world-"))
    os.chmod(path, 0o700)
    return path


def _execute(root: Path, argv: List[str], env: Dict[str, str], timeout: float,
             stdin: bytes) -> ExecResult:
    sandbox = _sandbox()
    caveats = _copy_world(root, sandbox)
    before, _ = _snapshot(sandbox)
    proc = subprocess.Popen(
        list(argv), cwd=str(sandbox), env=dict(env),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=(os.name == "posix"), preexec_fn=_limits(timeout),
    )
    timed_out = False
    try:
        stdout, stderr = proc.communicate(input=stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        stdout, stderr = proc.communicate()
        timed_out = True
    after, after_caveats = _snapshot(sandbox)
    blobs: Dict[str, bytes] = {}
    blob_total = 0
    for base in (root, sandbox):
        for rel, _ in _snapshot(base)[0].items():
            try:
                data = (base / rel).read_bytes()
            except OSError:
                continue
            digest = util.sha256_bytes(data)
            if digest in blobs:
                continue
            util.validate_limits(len(data), len(data), len(blobs) + 1)
            blob_total += len(data)
            if blob_total > util.MAX_BLOBS_TOTAL:
                _discard(sandbox)
                raise util.BugjarError(
                    "recorded world plus produced files exceed the cassette payload "
                    "limit (%d bytes); narrow --root or reduce command output"
                    % util.MAX_BLOBS_TOTAL)
            blobs[digest] = data
    if stdin:
        digest = util.sha256_bytes(stdin)
        if digest not in blobs:
            blob_total += len(stdin)
            if blob_total > util.MAX_BLOBS_TOTAL:
                _discard(sandbox)
                raise util.BugjarError("stdin pushes the cassette over its payload limit")
            blobs[digest] = stdin
    if proc.returncode is not None and proc.returncode < 0 and not timed_out:
        caveats.append("child was terminated by signal %d; observation may be partial"
                       % (-proc.returncode))
    if timed_out:
        caveats.append("wall-clock timeout after %.2fs; child process group was killed" % timeout)
    stdin_sha256 = util.sha256_bytes(stdin)
    for c in after_caveats:
        if c not in caveats:
            caveats.append(c)
    return ExecResult(sandbox, list(argv), dict(env), stdin_sha256, before, after,
                      proc.returncode if not timed_out else -9,
                      stdout or b"", stderr or b"", timed_out, blobs, caveats)


def _discard(path) -> None:
    try:
        import shutil
        shutil.rmtree(str(path), ignore_errors=True)
    except OSError:
        pass


def _cleanup(result: ExecResult) -> None:
    _discard(result.sandbox)


def _observe(result: ExecResult, before: Dict[str, str]) -> dict:
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


def _profile(argv: List[str]) -> dict:
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


def _profile_mismatches(recorded: dict, current: dict) -> List[str]:
    out = []
    for key in ("os", "machine", "python", "executable", "executable_sha256",
                "locale", "limits_available"):
        if recorded.get(key) != current.get(key):
            out.append("%s: recorded=%r current=%r" %
                       (key, recorded.get(key), current.get(key)))
    return out


def _build_manifest(argv, env_vars, redactions, stdin_sha256, before,
                    observation, caveats, timeout, repeat, lineage=None) -> dict:
    doc = {
        "format": util.FORMAT,
        "cassette_id": _new_id(),
        "created_utc": _now(),
        "command": {"argv": list(argv), "timeout_s": float(timeout),
                    "repeat": int(repeat)},
        "profile": _profile(argv),
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
    before, caveats = _snapshot(root)
    result = _execute(root, list(argv), env_vars, float(timeout), stdin_bytes)
    try:
        if result.timed_out:
            raise util.BugjarError("capture timed out after %.2fs" % timeout)
        observation = _observe(result, before)
        for c in result.caveats:
            if c not in caveats:
                caveats.append(c)
        doc = _build_manifest(argv, env_vars, redactions, result.stdin_sha256,
                              before, observation, caveats, timeout, repeat)
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
                "exit_code": observation["exit_code"],
                "created": len(observation["created"]),
                "modified": len(observation["modified"]),
                "deleted": len(observation["deleted"]),
                "stdout_bytes": observation["stdout"]["size"],
                "stderr_bytes": observation["stderr"]["size"],
            },
        }
    finally:
        _cleanup(result)


def _channels(recorded: dict, observed: dict) -> Dict[str, dict]:
    out = {}
    for name in CHANNELS:
        a, b = recorded.get(name), observed.get(name)
        if isinstance(a, dict) and isinstance(b, dict):
            match = util.canonical_json(a) == util.canonical_json(b)
        else:
            match = a == b
        out[name] = {"match": bool(match), "recorded": a, "observed": b}
    return out


def _same(a: dict, b: dict) -> bool:
    return util.canonical_json(a) == util.canonical_json(b)


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

    mismatches = _profile_mismatches(manifest.get("profile") or {},
                                     _profile(manifest["command"]["argv"]))
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
        sandbox = _sandbox()
        try:
            before = _restore(manifest, blobs, sandbox)
            expected = {i["path"]: i["sha256"] for i in manifest.get("inputs", [])}
            if before != expected:
                result["reasons"].append("input reconstruction mismatch")
                return result
            res = _execute(sandbox, argv, env, effective_timeout, stdin)
            try:
                if res.timed_out:
                    timeout_reason = "replay timeout after %.2fs" % effective_timeout
                    observations = []
                    break
                observations.append(_observe(res, before))
            finally:
                _cleanup(res)
        except util.BugjarError as exc:
            result["reasons"].append("replay failed: %s" % exc)
            return result
        finally:
            try:
                import shutil
                shutil.rmtree(str(sandbox), ignore_errors=True)
            except OSError:
                pass
    if timeout_reason:
        result["reasons"].append(timeout_reason)
        return result
    if not observations:
        result["reasons"].append("no replay completed")
        return result
    if len(observations) > 1 and any(not _same(observations[0], o)
                                     for o in observations[1:]):
        result["reasons"].append(
            "nondeterminism: repeated replays disagree; no majority vote is taken")
        return result
    first = observations[0]
    result["channels"] = _channels(recorded, first)
    mismatched = [c for c, v in result["channels"].items() if not v["match"]]
    if mismatched:
        result["verdict"] = "DIVERGED"
        result["reasons"].append("differing channels: " + ", ".join(sorted(mismatched)))
    else:
        result["verdict"] = "REPRODUCED"
    if redactions and allow_redacted:
        result["caveats"].append("verdict is weakened by --allow-redacted")
    return result


def _signature_match(recorded: dict, observed: dict, signature) -> bool:
    for name in signature:
        a, b = recorded.get(name), observed.get(name)
        if isinstance(a, dict) and isinstance(b, dict):
            if util.canonical_json(a) != util.canonical_json(b):
                return False
        elif a != b:
            return False
    return True


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
        sandbox = _sandbox()
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
                target_path = sandbox / rel
                target_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                target_path.write_bytes(data)
                os.chmod(target_path, 0o600)
                before[rel] = util.sha256_bytes(data)
            res = _execute(sandbox, argv, env, effective_timeout, stdin)
            try:
                if res.timed_out:
                    return False
                observed = _observe(res, before)
                return _signature_match(target, observed, sig)
            finally:
                _cleanup(res)
        finally:
            try:
                import shutil
                shutil.rmtree(str(sandbox), ignore_errors=True)
            except OSError:
                pass

    def oracle(subset):
        nonlocal calls
        calls += 1
        if calls > budget:
            raise BudgetExhausted()
        # A candidate with no input files can "reproduce" a trivial
        # interpreter error. Refuse that unless the operator opts in.
        if not allow_empty_world and file_units and not any(
                not u.startswith("env:") for u in subset):
            return False
        return candidate(subset)

    try:
        current = _ddmin(units, oracle)
        if not oracle(current):
            return {"action": "shrink", "verdict": "ORACLE_UNSTABLE",
                    "reason": "final candidate did not preserve the failure signature",
                    "oracle_calls": calls}
    except BudgetExhausted:
        return {"action": "shrink", "verdict": "BUDGET_EXHAUSTED",
                "reason": "replay budget exhausted before 1-minimality",
                "oracle_calls": calls, "budget": budget, "out": str(out)}

    kept = sorted(current)
    removed = sorted(set(units) - set(kept))
    file_set = [u for u in kept if not u.startswith("env:")]
    env_set = {u[4:] for u in kept if u.startswith("env:")}
    final_env = {k: v for k, v in stored_env.items() if k in env_set}
    final_env.update(util.NORMALIZATION)
    final_world = _sandbox()
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
        res = _execute(final_world, argv, final_env, effective_timeout, stdin)
        try:
            if res.timed_out:
                return {"action": "shrink", "verdict": "TIMEOUT",
                        "reason": "final capture timed out", "oracle_calls": calls}
            observation = _observe(res, before)
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
            doc = _build_manifest(argv, final_env, [], res.stdin_sha256, before,
                                  observation, caveats, effective_timeout, 1,
                                  lineage=lineage)
            cassette.save(out, doc, res.blobs, sign_key=sign_key)
        finally:
            _cleanup(res)
    finally:
        try:
            import shutil
            shutil.rmtree(str(final_world), ignore_errors=True)
        except OSError:
            pass

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


def _ddmin(units: List[str], oracle) -> List[str]:
    """Delta debugging: complement testing at increasing granularity, then 1-minimal."""
    current = list(units)
    granularity = 2
    while len(current) >= 2:
        chunks = [current[i::granularity] for i in range(granularity)]
        chunks = [c for c in chunks if c]
        reduced = False
        for chunk in chunks:
            drop = set(chunk)
            complement = [u for u in current if u not in drop]
            if complement and oracle(complement):
                current = complement
                granularity = max(2, granularity - 1)
                reduced = True
                break
        if not reduced:
            if granularity >= len(current):
                break
            granularity = min(len(current), granularity * 2)
    changed = True
    while changed:
        changed = False
        for unit in list(current):
            complement = [u for u in current if u != unit]
            if oracle(complement):
                current = complement
                changed = True
    return current


def _flatten(obj, prefix=""):
    if isinstance(obj, dict):
        for key in sorted(obj):
            yield from _flatten(obj[key], prefix + "." + str(key) if prefix else str(key))
    elif isinstance(obj, (list, tuple)):
        for i, value in enumerate(obj):
            yield from _flatten(value, "%s[%d]" % (prefix, i))
    else:
        yield prefix, obj


VOLATILE = ("cassette_id", "created_utc", "integrity", "signature", "lineage")


def diff(a, b) -> dict:
    ma, _ = cassette.load(a)
    mb, _ = cassette.load(b)
    fa = {k: v for k, v in _flatten(ma) if k.split(".")[0] not in VOLATILE}
    fb = {k: v for k, v in _flatten(mb) if k.split(".")[0] not in VOLATILE}
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
    mismatches = _profile_mismatches(manifest.get("profile") or {},
                                     _profile(manifest["command"]["argv"]))
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
