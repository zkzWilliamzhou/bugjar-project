"""The Runner seam: everything about sandboxes, process limits and snapshots.

Deep interface: callers pass a World directory plus argv/env/stdin and receive
one ExecResult. Temp directories, rlimits, process groups, symlink handling and
content-addressed blob collection stay behind this boundary.
"""
from __future__ import annotations

import os
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

from . import cassette, util


def snapshot(root: Path) -> Tuple[Dict[str, str], List[str]]:
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


def copy_world(root: Path, dst: Path) -> List[str]:
    caveats: List[str] = []
    total = 0
    for rel, digest in sorted(snapshot(root)[0].items()):
        src = root / rel
        data = src.read_bytes()
        total += len(data)
        util.validate_limits(total, len(data), 0)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_bytes(data)
        os.chmod(target, 0o600)
    for rel in snapshot(root)[1]:
        caveats.append(rel)
    return caveats


def restore(manifest: dict, blobs: Dict[str, bytes], dst: Path) -> Dict[str, str]:
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


def sandbox() -> Path:
    path = Path(tempfile.mkdtemp(prefix="bugjar-world-"))
    os.chmod(path, 0o700)
    return path


def discard(path) -> None:
    try:
        import shutil
        shutil.rmtree(str(path), ignore_errors=True)
    except OSError:
        pass


def cleanup(result: ExecResult) -> None:
    discard(result.sandbox)


def limits(timeout: float):
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


def kill_group(proc: subprocess.Popen) -> None:
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


def execute(root: Path, argv: List[str], env: Dict[str, str], timeout: float,
            stdin: bytes) -> ExecResult:
    dst = sandbox()
    caveats = copy_world(root, dst)
    before, _ = snapshot(dst)
    proc = subprocess.Popen(
        list(argv), cwd=str(dst), env=dict(env),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=(os.name == "posix"), preexec_fn=limits(timeout),
    )
    timed_out = False
    try:
        stdout, stderr = proc.communicate(input=stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_group(proc)
        stdout, stderr = proc.communicate()
        timed_out = True
    after, after_caveats = snapshot(dst)
    blobs: Dict[str, bytes] = {}
    blob_total = 0
    for base in (root, dst):
        for rel, _ in snapshot(base)[0].items():
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
                discard(dst)
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
                discard(dst)
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
    return ExecResult(dst, list(argv), dict(env), stdin_sha256, before, after,
                      proc.returncode if not timed_out else -9,
                      stdout or b"", stderr or b"", timed_out, blobs, caveats)
