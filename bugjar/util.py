"""Small, dependency-free primitives shared by the cassette and the runner."""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Dict, Iterable, List, Tuple

FORMAT = "bugjar/1"
VERSION = "1.0.0"

MAX_BLOB_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_MEMBERS = 5000
MAX_TREE_BYTES = 64 * 1024 * 1024
# A cassette also carries README.txt and manifest.json. Leaving headroom here
# guarantees that anything capture writes can be loaded back by cassette.load.
MAX_BLOBS_TOTAL = MAX_TOTAL_BYTES - MAX_MANIFEST_BYTES - 65536

SECRET_MARKERS = (
    "TOKEN", "SECRET", "PASSWORD", "PASSWD", "API_KEY", "APIKEY",
    "PRIVATE_KEY", "CREDENTIAL", "ACCESS_KEY", "BEARER", "SESSION_KEY",
    "CLIENT_SECRET", "AUTH_TOKEN",
)

NORMALIZATION = {
    "LANG": "C",
    "LC_ALL": "C",
    "TZ": "UTC",
    "PYTHONHASHSEED": "0",
    "PYTHONIOENCODING": "utf-8",
    "SOURCE_DATE_EPOCH": "1700000000",
}

SAFE_ENV_KEYS = (
    "PATH", "LANG", "LC_ALL", "TZ", "PYTHONHASHSEED",
    "PYTHONIOENCODING", "SOURCE_DATE_EPOCH", "SYSTEMROOT",
)


class BugjarError(Exception):
    """A user-visible, non-recoverable condition."""


def canonical_json(obj: Any) -> bytes:
    """Deterministic, compact, ASCII JSON. Used for digests and signatures."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_rel_path(path: str) -> str:
    """Return a normalized POSIX relative path, or refuse it.

    Refuses absolute paths, drive letters, UNC paths, backslashes, NUL bytes,
    empty components, '.' and '..' components, and trailing separators.
    """
    if not isinstance(path, str) or not path:
        raise BugjarError("empty or non-string path")
    if "\x00" in path:
        raise BugjarError("NUL byte in path: %r" % path[:64])
    if "\\" in path:
        raise BugjarError("backslash in path: %r" % path[:64])
    if re.match(r"^[A-Za-z]:", path):
        raise BugjarError("drive letter in path: %r" % path[:64])
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise BugjarError("unsafe path component: %r" % path[:64])
    return "/".join(parts)


def is_secret_key(key: str) -> bool:
    upper = str(key).upper()
    return any(marker in upper for marker in SECRET_MARKERS)


def redact_env(env: Dict[str, str], allow: Iterable[str] = (),
               force_redact: Iterable[str] = ()) -> Tuple[Dict[str, str], List[dict]]:
    """Return a recordable environment plus an auditable redaction list."""
    allowed = set(allow)
    forced = set(force_redact)
    out: Dict[str, str] = {}
    forced_list: List[dict] = []
    auto_list: List[dict] = []
    for key in sorted(env):
        value = str(env[key])
        if key in allowed:
            out[key] = value
            continue
        if key in forced or is_secret_key(key):
            digest = sha256_bytes(value.encode("utf-8", "replace"))
            out[key] = "<redacted:%s>" % digest[:12]
            entry = {
                "key": key,
                "sha256": digest,
                "reason": "explicit --env-redact" if key in forced else "secret-shaped key",
            }
            (forced_list if key in forced else auto_list).append(entry)
        else:
            out[key] = value
    # Explicit user decisions are reported before automatic detections.
    return out, forced_list + auto_list


def prepare_env(env_base: Dict[str, str], allow: Iterable[str] = (),
                force_redact: Iterable[str] = ()) -> Tuple[Dict[str, str], List[dict]]:
    """Force a fixed normalization layer, then redact.

    Capture and replay both use exactly the returned dict, so the witness
    channel is comparable without re-deriving host state.
    """
    raw = {str(k): str(v) for k, v in env_base.items()}
    raw.update(NORMALIZATION)
    return redact_env(raw, allow=allow, force_redact=force_redact)


def controlled_environment(base: Dict[str, str], extra: Iterable[str] = ()) -> Dict[str, str]:
    """The CLI exposes only a curated allow-list of the host environment."""
    out = {k: base[k] for k in SAFE_ENV_KEYS if k in base}
    for key in extra:
        if key not in base:
            raise BugjarError("--env %s is not set in the current environment" % key)
        out[key] = base[key]
    return out


def normalize_text(data: bytes, sandbox_root: str) -> bytes:
    """Erase per-run temp paths and line-ending differences from output bytes."""
    text = data.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
    for candidate in {str(sandbox_root), os.path.realpath(str(sandbox_root)),
                      str(sandbox_root).replace("\\", "/")}:
        if candidate:
            text = text.replace(candidate, "<WORLD>")
    text = re.sub(r"[^\s\"'<>]*bugjar-world-[A-Za-z0-9_]+", "<WORLD>", text)
    return text.encode("utf-8")


def preview(data: bytes, limit: int = 240) -> str:
    text = data.decode("utf-8", "replace")
    if len(text) > limit:
        return text[:limit] + "...<truncated>"
    return text


def witness(argv: List[str], env: Dict[str, str], stdin_sha256: str,
            inputs: Dict[str, str]) -> str:
    """Digest of the restored input world. Channel 7 of the observation."""
    payload = {
        "argv": list(argv),
        "env": env,
        "stdin_sha256": stdin_sha256,
        "inputs": inputs,
    }
    return sha256_bytes(canonical_json(payload))


def validate_limits(total: int, per_file: int, members: int) -> None:
    if per_file > MAX_BLOB_BYTES:
        raise BugjarError("file exceeds %d byte limit" % MAX_BLOB_BYTES)
    if total > MAX_TOTAL_BYTES:
        raise BugjarError("tree exceeds %d byte limit" % MAX_TOTAL_BYTES)
    if members > MAX_MEMBERS:
        raise BugjarError("too many members: %d > %d" % (members, MAX_MEMBERS))
