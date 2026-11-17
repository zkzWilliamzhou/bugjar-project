"""Command line interface. argv lists only; no shell is ever involved."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import engine, util


def _json(doc) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=True)


def _read_key(value):
    if value is None:
        return None
    p = Path(value)
    if not p.is_file():
        raise util.BugjarError("key file not found: %s" % p)
    data = p.read_bytes()
    if len(data) < 8:
        raise util.BugjarError("key file is too short (need at least 8 bytes)")
    return data


def _out(doc, as_json, text=None):
    if as_json:
        print(_json(doc))
    elif text is not None:
        print(text, end="" if text.endswith("\n") else "\n")
    else:
        print(_json(doc))
    return 0


def _verdict_code(verdict: str) -> int:
    return {"REPRODUCED": 0, "DIVERGED": 1, "UNVERIFIABLE": 2}.get(verdict, 3)


def build_parser():
    p = argparse.ArgumentParser(prog="bugjar", description="Put a failing command in a jar.")
    p.add_argument("--version", action="version", version="bugjar " + util.VERSION)
    sub = p.add_subparsers(dest="cmd")

    r = sub.add_parser("run", help="record a command into a cassette")
    r.add_argument("--root", default=".", help="input world directory")
    r.add_argument("--stdin", default=None, help="file to feed on stdin")
    r.add_argument("--env", action="append", default=[], metavar="KEY",
                   help="expose one more host environment variable")
    r.add_argument("--env-redact", action="append", default=[], metavar="KEY",
                   help="force redaction of a variable")
    r.add_argument("--timeout", type=float, default=10.0)
    r.add_argument("--out", required=True)
    r.add_argument("--sign", default=None, metavar="KEYFILE")
    r.add_argument("--repeat", type=int, default=1)
    r.add_argument("--json", action="store_true")
    r.add_argument("command", nargs=argparse.REMAINDER)

    v = sub.add_parser("verify", help="replay and return a strict verdict")
    v.add_argument("cassette")
    v.add_argument("--repeat", type=int, default=1)
    v.add_argument("--timeout", type=float, default=None)
    v.add_argument("--key", default=None, metavar="KEYFILE")
    v.add_argument("--allow-redacted", action="store_true")
    v.add_argument("--json", action="store_true")

    s = sub.add_parser("shrink", help="delta-debug the recorded world")
    s.add_argument("cassette")
    s.add_argument("--out", required=True)
    s.add_argument("--budget", type=int, default=200)
    s.add_argument("--signature", default="exit_code,stderr,stdout")
    s.add_argument("--timeout", type=float, default=None)
    s.add_argument("--allow-redacted", action="store_true")
    s.add_argument("--allow-empty-world", action="store_true",
                   help="permit a minimizer candidate with zero input files")
    s.add_argument("--sign", default=None, metavar="KEYFILE")
    s.add_argument("--json", action="store_true")

    d = sub.add_parser("diff", help="compare two cassettes")
    d.add_argument("a")
    d.add_argument("b")
    d.add_argument("--out", default=None)
    d.add_argument("--json", action="store_true")

    e = sub.add_parser("explain", help="evidence-linked Markdown report")
    e.add_argument("cassette")
    e.add_argument("--out", default=None)

    c = sub.add_parser("doctor", help="check profile and integrity")
    c.add_argument("cassette")
    c.add_argument("--json", action="store_true")

    sub.add_parser("version", help="print the version")
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.cmd or args.cmd == "version":
        print("bugjar " + util.VERSION)
        return 0
    try:
        if args.cmd == "run":
            command = list(args.command)
            if command and command[0] == "--":
                command = command[1:]
            if not command:
                raise util.BugjarError("empty command: pass a command after --")
            if args.timeout <= 0:
                raise util.BugjarError("--timeout must be positive")
            if args.repeat < 1:
                raise util.BugjarError("--repeat must be at least 1")
            env_base = util.controlled_environment(dict(os.environ), extra=args.env)
            stdin_bytes = b""
            if args.stdin:
                p = Path(args.stdin)
                if not p.is_file():
                    raise util.BugjarError("stdin file not found: %s" % p)
                stdin_bytes = p.read_bytes()
                util.validate_limits(len(stdin_bytes), len(stdin_bytes), 1)
            doc = engine.run(args.root, command, args.out, env_base,
                             timeout=args.timeout, stdin_bytes=stdin_bytes,
                             env_redact=args.env_redact,
                             sign_key=_read_key(args.sign), repeat=args.repeat)
            return _out(doc, args.json, text="recorded %s -> %s" %
                        (" ".join(command), doc["out"]))

        if args.cmd == "verify":
            if args.repeat < 1:
                raise util.BugjarError("--repeat must be at least 1")
            if args.timeout is not None and args.timeout <= 0:
                raise util.BugjarError("--timeout must be positive")
            doc = engine.verify(args.cassette, repeat=args.repeat,
                                timeout=args.timeout, key=_read_key(args.key),
                                allow_redacted=args.allow_redacted)
            code = _verdict_code(doc["verdict"])
            _out(doc, args.json, text="%s %s" % (doc["verdict"], doc["cassette"]))
            return code

        if args.cmd == "shrink":
            signature = tuple(x.strip() for x in args.signature.split(",") if x.strip())
            if args.budget < 1:
                raise util.BugjarError("--budget must be at least 1")
            if args.timeout is not None and args.timeout <= 0:
                raise util.BugjarError("--timeout must be positive")
            doc = engine.shrink(args.cassette, args.out, budget=args.budget,
                                signature=signature, timeout=args.timeout,
                                allow_redacted=args.allow_redacted,
                                allow_empty_world=args.allow_empty_world,
                                sign_key=_read_key(args.sign))
            _out(doc, args.json, text="%s %s" % (doc["verdict"], args.out))
            return 0 if doc["verdict"] == "SHRUNK" else 2

        if args.cmd == "diff":
            doc = engine.diff(args.a, args.b)
            text = _json(doc)
            if args.out:
                Path(args.out).write_text(text + "\n", encoding="utf-8")
            return _out(doc, args.json, text=text)

        if args.cmd == "explain":
            text = engine.explain(args.cassette)
            if args.out:
                Path(args.out).write_text(text, encoding="utf-8")
            print(text, end="")
            return 0

        if args.cmd == "doctor":
            doc = engine.doctor(args.cassette)
            return _out(doc, args.json, text="comparable=%s integrity=%s" %
                        (doc["comparable"], doc["integrity"]))
    except util.BugjarError as exc:
        print("bugjar: %s" % exc, file=sys.stderr)
        return 3
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("bugjar: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 3
    return 3
