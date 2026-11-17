# Security policy

bugjar reads untrusted `.bugjar` files and executes commands recorded inside them. Treat a cassette like a program, not like data.

## Threat model

An attacker may control the whole cassette: member names, zip metadata, blob bytes, the manifest, the argv list, environment values, and input file contents. The tool's job is to refuse malformed or hostile archives before anything is written to disk, and to run recorded commands inside a disposable sandbox.

## Archive parsing

`cassette.load` performs these checks before returning any bytes:

- `manifest.json` must exist and must be a JSON object. No `pickle`, `yaml`, `eval`, or custom `object_hook`.
- Every member name goes through `safe_rel_path`: relative POSIX, no `..`, no `.`, no empty component, no absolute path, no drive letter, no UNC prefix, no backslash, no NUL byte, no trailing slash.
- Only `README.txt`, `manifest.json`, and `blobs/<64 lowercase hex>` are allowed.
- Blob members must be regular files. Symlinks, devices, directories, and encrypted members are refused.
- Duplicate member names are refused. Member count is capped at 5,000.
- Each blob is capped at 8 MiB; total uncompressed size at 64 MiB; the manifest at 1 MiB.
- Blob bytes are read manually. `zipfile.extractall` is never used. Nothing from the archive is written to the host filesystem by the loader.
- Every blob member name must equal the SHA-256 of its contents, and the manifest must list that member with the same digest.
- `integrity.root` is recomputed from the canonical manifest minus `root`/`signature`, plus the sorted blob digests. Comparison uses `hmac.compare_digest`.
- `cassette.save` writes to a temporary sibling file and atomically replaces the target.

The adversarial suite generates 23 hostile cassettes and asserts all 23 are refused: `python3 tools/adversarial.py`.

## Command execution

- argv is a list. `shell=True` is never used anywhere in the codebase; `tools/hygiene.py` enforces this.
- The command runs in a fresh `0o700` temp directory. Input files are written with `0o600`.
- On POSIX, `setrlimit` caps CPU, file size, open files, and core dumps. A wall-clock timeout kills the whole process group with `SIGKILL`.
- A child killed by a signal is recorded with a caveat saying the observation may be partial.
- The tool itself makes no network calls. No socket, HTTP client, pickle, or YAML module is imported.
- Network access and the wall clock of the recorded command are outside the model. They are documented caveats, not virtualized guarantees.

## Secrets

- The CLI exposes only a curated allow-list of host variables. Host secrets are not captured by default.
- Keys matching `TOKEN`, `SECRET`, `PASSWORD`, `API_KEY`, `CREDENTIAL`, `ACCESS_KEY`, `BEARER`, `PRIVATE_KEY`, `SESSION_KEY`, `AUTH_TOKEN`, or `CLIENT_SECRET` have their values replaced by `<redacted:...>` and are listed in `environment.redactions` with a SHA-256 of the original value.
- A redacted value does not reproduce the original environment. `verify` returns `UNVERIFIABLE`. `--allow-redacted` produces `REPRODUCED` only with explicit caveats.
- The redaction list itself contains key names and digests, not values. If a key name is sensitive in your context, do not record it.

## Integrity is not authenticity

`integrity.root` detects modification if the verifier trusts the checksum and the machine that computed it. An attacker who can rewrite the cassette can recompute the root. `--sign KEYFILE` adds `HMAC-SHA256` with a local shared key:

- `key_id` is a 16-hex prefix of the key digest, not an identity.
- The HMAC covers the integrity root. It proves the holder of the key produced or approved that root.
- It does not prove the captured run was faithful, that the command was benign, or that the profile is complete.
- There is no transparency log, no public key infrastructure, and no signature over real-world identity.
- A signed cassette loaded without `--key` is refused. An unsigned cassette loaded with `--key` is refused. A wrong key is refused.

Do not treat `REPRODUCED` as "this code is safe". It means seven recorded channels matched under a comparable profile.

## Resource limits

| Limit | Value |
|---|---|
| Per blob | 8 MiB |
| Total uncompressed | 64 MiB |
| Blob payload headroom | 64 MiB − 1 MiB manifest − 64 KiB |
| Manifest | 1 MiB |
| Zip members | 5,000 |
| Stdin | 8 MiB |
| Default wall-clock timeout | 10 s |
| Default shrink oracle budget | 200 replays |

`runner.execute` accumulates unique blob bytes across both the input tree and the produced tree, so a cassette that capture writes can always be read back by `cassette.load`.

## Reporting a vulnerability

Open an issue with a hostile cassette that `cassette.load` accepts, or a command that escapes the sandbox. Include the exact `bugjar` command, the Python version, and the OS. A reproducible refusal failure gets a regression test in `tools/adversarial.py` before any fix is merged.
