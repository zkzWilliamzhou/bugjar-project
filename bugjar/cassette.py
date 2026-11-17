"""The .bugjar cassette: one ZIP, one canonical manifest, content-addressed blobs.

Security boundary: no extractall, no absolute or traversing member names, no
symlink members, no duplicate names, no encrypted members, hard size caps, and a
recomputed integrity root on every load.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import re
import stat
import zipfile
from pathlib import Path
from typing import Dict, Optional, Tuple

from . import util

MANIFEST = "manifest.json"
README = "README.txt"
BLOB_PREFIX = "blobs/"
HEX64 = re.compile(r"^[0-9a-f]{64}$")

README_TEXT = """\
bugjar cassette (format bugjar/1)

One failing command, its input world, and its observed output world in one file.
Read with:  bugjar doctor <file>   /   bugjar explain <file>
Verify:     bugjar verify <file>
Shrink:     bugjar shrink <file> --out <minimal.bugjar>

The integrity root is a local checksum. It detects modification if the
verifier trusts the checksum and the machine that computed it. It is not
authenticity. An optional HMAC provides a local shared-key check only.
See SECURITY.md in the project.
"""


def _blob_names(blobs: Dict[str, bytes]) -> Dict[str, bytes]:
    """Accept keys as bare digests or as `blobs/<digest>` member names."""
    out: Dict[str, bytes] = {}
    for key, value in blobs.items():
        name = str(key)
        if not name.startswith(BLOB_PREFIX):
            name = BLOB_PREFIX + name
        util.safe_rel_path(name)
        hexpart = name[len(BLOB_PREFIX):]
        if not HEX64.match(hexpart):
            raise util.BugjarError("blob member is not named by a sha256 digest: %r" % name[:80])
        if not isinstance(value, bytes):
            raise util.BugjarError("blob payload is not bytes")
        util.validate_limits(len(value), len(value), 1)
        out[name] = value
    return out


def compute_root(manifest: dict, blobs: Dict[str, bytes]) -> str:
    """SHA-256 over canonical manifest (minus root/signature) + sorted blob digests."""
    core = {k: v for k, v in manifest.items() if k != "signature"}
    core["integrity"] = {k: v for k, v in manifest.get("integrity", {}).items()
                         if k != "root"}
    listing = "\n".join("%s:%s" % (n, util.sha256_bytes(blobs[n]))
                        for n in sorted(blobs))
    payload = util.canonical_json(core) + b"\n" + listing.encode("ascii")
    return util.sha256_bytes(payload)


def _signature_for(key: bytes, root: str) -> dict:
    return {
        "scheme": "hmac-sha256-local",
        "note": "Local shared key. Not a digital signature and not identity.",
        "key_id": util.sha256_bytes(key)[:16],
        "value": hmac.new(key, root.encode("ascii"), hashlib.sha256).hexdigest(),
    }


def integrity_problems(manifest: dict, blobs: Dict[str, bytes],
                       key: Optional[bytes] = None) -> list:
    """Return a list of problems. Empty list means the cassette checks out."""
    problems = []
    if not isinstance(manifest, dict):
        return ["manifest is not an object"]
    if manifest.get("format") != util.FORMAT:
        problems.append("unsupported format: %r" % manifest.get("format"))
    integrity = manifest.get("integrity") or {}
    if integrity.get("algorithm") != "sha256":
        problems.append("unsupported integrity algorithm")
    if not HEX64.match(str(integrity.get("root", ""))):
        problems.append("malformed integrity root")
    for name, data in sorted(blobs.items()):
        hexpart = name[len(BLOB_PREFIX):] if name.startswith(BLOB_PREFIX) else name
        if not HEX64.match(hexpart):
            problems.append("blob name is not a digest: %s" % name)
        elif not hmac.compare_digest(hexpart, util.sha256_bytes(data)):
            problems.append("blob digest mismatch: %s" % name)
        recorded = (integrity.get("members") or {}).get(name)
        if recorded is None:
            problems.append("blob not listed in manifest: %s" % name)
        elif not hmac.compare_digest(str(recorded), util.sha256_bytes(data)):
            problems.append("blob digest mismatch against manifest: %s" % name)
    listed = set((integrity.get("members") or {}).keys())
    for extra in sorted(listed - set(blobs)):
        problems.append("manifest lists missing blob: %s" % extra)
    try:
        actual = compute_root(manifest, blobs)
    except (TypeError, ValueError, util.BugjarError) as exc:
        return problems + ["cannot recompute integrity root: %s" % exc]
    if not hmac.compare_digest(str(integrity.get("root", "")), actual):
        problems.append("integrity root mismatch")

    signature = manifest.get("signature")
    if key is not None:
        if not isinstance(signature, dict):
            problems.append("signature required by --key but cassette is unsigned")
        else:
            expected = _signature_for(key, str(integrity.get("root", "")))
            if signature.get("scheme") != expected["scheme"]:
                problems.append("unsupported signature scheme")
            elif not hmac.compare_digest(str(signature.get("value", "")), expected["value"]):
                problems.append("signature verification failed")
    elif signature is not None:
        problems.append("cassette is signed but no --key was supplied")
    return problems


def verify_integrity(manifest: dict, blobs: Dict[str, bytes],
                     key: Optional[bytes] = None) -> list:
    """Pure check used by tests and by the doctor command."""
    named = _blob_names(blobs) if any(
        not str(k).startswith(BLOB_PREFIX) for k in blobs) else dict(blobs)
    return integrity_problems(manifest, named, key=key)


def save(path, manifest: dict, blobs: Dict[str, bytes],
         sign_key: Optional[bytes] = None) -> str:
    """Write a cassette atomically and return its integrity root."""
    blobs = _blob_names(blobs)
    doc = copy.deepcopy(manifest)
    doc["format"] = util.FORMAT
    doc["integrity"] = {
        "algorithm": "sha256",
        "members": {n: util.sha256_bytes(blobs[n]) for n in sorted(blobs)},
        "root": "",
    }
    doc["signature"] = None
    doc["integrity"]["root"] = compute_root(doc, blobs)
    if sign_key is not None:
        doc["signature"] = _signature_for(sign_key, doc["integrity"]["root"])

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in (README, MANIFEST):
            info = zipfile.ZipInfo(name)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zout.writestr(info, README_TEXT.encode("utf-8") if name == README
                          else util.canonical_json(doc))
        for name in sorted(blobs):
            info = zipfile.ZipInfo(name)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zout.writestr(info, blobs[name])
    tmp.replace(target)
    return doc["integrity"]["root"]


def load(path, key: Optional[bytes] = None) -> Tuple[dict, Dict[str, bytes]]:
    """Read and fully validate a cassette. Never writes to the host filesystem."""
    target = Path(path)
    try:
        if not target.is_file():
            raise util.BugjarError("cassette not found: %s" % target)
        with zipfile.ZipFile(target) as zin:
            infos = zin.infolist()
            if len(infos) > util.MAX_MEMBERS:
                raise util.BugjarError("too many zip members")
            names = [i.filename for i in infos]
            if len(set(names)) != len(names):
                raise util.BugjarError("duplicate zip member")
            total = 0
            for info in infos:
                name = info.filename
                util.safe_rel_path(name)
                mode = stat.S_IFMT(info.external_attr >> 16)
                if mode == stat.S_IFLNK:
                    raise util.BugjarError("symlink member refused: %s" % name)
                if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise util.BugjarError("special file member refused: %s" % name)
                if info.flag_bits & 0x1:
                    raise util.BugjarError("encrypted member refused: %s" % name)
                if name not in (MANIFEST, README) and not name.startswith(BLOB_PREFIX):
                    raise util.BugjarError("unexpected member: %s" % name)
                if name.startswith(BLOB_PREFIX):
                    if mode not in (0, stat.S_IFREG):
                        raise util.BugjarError("blob member is not a regular file: %s" % name)
                    if not HEX64.match(name[len(BLOB_PREFIX):]):
                        raise util.BugjarError("blob member is not a digest: %s" % name)
                declared = info.file_size
                if declared > util.MAX_BLOB_BYTES and name.startswith(BLOB_PREFIX):
                    raise util.BugjarError("oversized blob: %s" % name)
                total += declared
                if total > util.MAX_TOTAL_BYTES:
                    raise util.BugjarError("uncompressed size exceeds limit")
            if MANIFEST not in names:
                raise util.BugjarError("missing manifest.json")
            raw = zin.read(MANIFEST)
            if len(raw) > util.MAX_MANIFEST_BYTES:
                raise util.BugjarError("oversized manifest")
            doc = json.loads(raw.decode("utf-8"))
            if not isinstance(doc, dict):
                raise util.BugjarError("manifest is not a JSON object")
            blobs: Dict[str, bytes] = {}
            for info in infos:
                if not info.filename.startswith(BLOB_PREFIX):
                    continue
                data = zin.read(info.filename)
                if len(data) > util.MAX_BLOB_BYTES:
                    raise util.BugjarError("oversized blob after read: %s" % info.filename)
                blobs[info.filename] = data
            problems = integrity_problems(doc, blobs, key=key)
            if problems:
                raise util.BugjarError("; ".join(problems))
            return doc, blobs
    except zipfile.BadZipFile as exc:
        raise util.BugjarError("not a valid zip cassette: %s" % exc) from exc
    except (OSError, ValueError, UnicodeError, KeyError, TypeError,
            json.JSONDecodeError) as exc:
        raise util.BugjarError("cannot read cassette: %s" % exc) from exc
