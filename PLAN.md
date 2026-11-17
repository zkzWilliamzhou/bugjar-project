# Implementation plan (frozen after this document)

Scope is frozen. A8 (architecture refactor) may change structure only; behavior changes are an automatic rejection.

## Product

`bugjar`, Python 3.9+, standard library only, offline, single portable `.bugjar` cassette (ZIP) per recorded run.

## CLI

```
bugjar run     --root DIR --stdin FILE --env KEY --env-redact KEY --timeout S
               --out FILE --sign KEYFILE -- <command> [args...]
bugjar verify  FILE [--repeat N] [--timeout S] [--key KEYFILE] [--json]
bugjar shrink  FILE --out FILE [--budget N] [--signature exit,stderr] [--timeout S]
bugjar diff    A B [--out FILE]
bugjar explain FILE [--out FILE]
bugjar doctor  FILE
bugjar version
```

## Cassette schema (`bugjar/1`)

ZIP members: `manifest.json`, `blobs/<sha256>` (content-addressed), `README.txt`. No absolute paths, no `..`, no symlink members, no duplicate names, no encryption.

`manifest.json` keys: `format`, `cassette_id`, `created_utc`, `command` (argv, timeout_s, repeat), `profile` (os, machine, python, executable path + digest, locale, limits_available, normalization), `environment` (`vars`, `redactions`), `stdin_sha256`, `inputs` (path, digest, size, mode), `observation` (7 channels), `caveats`, `integrity` (`algorithm`, `root`, `members`), `signature` (optional HMAC-SHA256: scheme, key_id, value).

`integrity.root` = SHA-256 over canonical JSON of the manifest with `integrity.root` and `signature` omitted, concatenated with the sorted `name:digest` list of all blob members. Verification recomputes it from disk. This is integrity, not authenticity.

## Seven observation channels

1. `exit_code`
2. `stdout` (digest + size + preview)
3. `stderr`
4. `created` files (relative path -> digest)
5. `modified` files
6. `deleted` files
7. `witness` — digest of the restored input world (argv + stdin + normalized env + input files), proving replay used the same inputs

Comparison normalizes the sandbox root path in stdout/stderr to `<WORLD>` and sorts all path lists. Timing is never a channel.

## Verdict semantics (strict, three-valued)

- `REPRODUCED`: all 7 channels match under a comparable profile and valid integrity.
- `DIVERGED`: replay completed under a comparable profile, but at least one channel differs; the exact channel and both values are reported.
- `UNVERIFIABLE`: integrity failure, missing blob, toolchain/profile mismatch, timeout, limit unavailable, required redacted variable, signature required but missing/invalid, unsafe cassette. Never reported as success.

`--repeat N` runs N replays; a split result is `UNVERIFIABLE` with a nondeterminism reason, not a majority vote.

## Security boundary

- argv list only, never `shell=True`.
- All cassette paths validated on write and read: relative, POSIX-normalized, no `..`, no absolute, no drive/UNC, no NUL, no symlink members, no duplicates.
- Caps: 8 MiB per blob, 64 MiB total uncompressed, 5000 members, 64 MiB source tree at capture.
- Env: secret-shaped keys redacted by default; redactions recorded; replay with a redacted value that the command needs is `UNVERIFIABLE`.
- Fresh 0o700 temp sandbox; manual member copy (never `extractall`); `resource.setrlimit` on POSIX for CPU/FSIZE/NOFILE plus a wall-clock timeout; no network calls from the tool.
- HMAC via `hmac.compare_digest`; unsigned cassettes are explicitly labeled unsigned.
- JSON only; no `pickle`, `eval`, `yaml`, or `object_hook`.

## Modules (v1 baseline)

`__init__.py`, `util.py`, `cassette.py`, `engine.py`, `cli.py`, `__main__.py`. `engine.py` is deliberately the first working version: it will be examined by the architecture refactor.

## Test strategy

- TDD: tests written first, RED observed, then implementation to GREEN.
- Unit: canonical JSON, path validation, env redaction, integrity.
- Integration: run/verify/shrink/diff/explain/doctor on fixture commands.
- Adversarial: zip slip, absolute path, symlink member, duplicate member, oversized blob, corrupt digest, corrupt manifest, truncation, secret env, argv injection, timeout, unicode paths.
- Golden matrix: ~24 normalized CLI outputs captured from the frozen v1 baseline and compared byte-for-byte after the refactor.
- Nine or more numbered review rounds, each with a distinct focus, a real command, and a real result.

## Milestones

M1 docs + skills -> M2 tests RED -> M3 implementation GREEN -> M4 rounds 1-9 -> M5 freeze baseline + goldens -> M6 architecture report + refactor -> M7 golden equality + final audit -> M8 release zip.
