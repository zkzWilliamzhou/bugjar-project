# bugjar

Put a failing command in a jar.

`bugjar run` records one command, its input world, and everything it did into a single `.bugjar` file. `bugjar verify` replays it and returns one of exactly three answers. `bugjar shrink` cuts the recorded world down to the smallest set of files and environment variables that still produces the original failure.

```bash
python3 -m bugjar run --root ./repro --out bug.bugjar -- python3 repro.py
python3 -m bugjar verify bug.bugjar --json
python3 -m bugjar shrink bug.bugjar --out min.bugjar --json
python3 -m bugjar explain bug.bugjar
```

Python 3.9+, standard library only, offline, no install step, no telemetry.

## What the cassette holds

A `.bugjar` is a ZIP with a canonical `manifest.json` and content-addressed blobs under `blobs/`. The manifest records argv, a filtered environment, stdin, every input file, toolchain fingerprints, and seven observation channels:

1. `exit_code`
2. `stdout`
3. `stderr`
4. created files
5. modified files
6. deleted files
7. `witness` — a digest of the restored input world

Timing is not a channel. A shrunk cassette is a new cassette with its own observation; it is never compared against its parent's observation and declared equal.

## Three verdicts, never two

| Verdict | Meaning |
|---|---|
| `REPRODUCED` | All seven channels match under a comparable profile and valid integrity. |
| `DIVERGED` | Replay finished; at least one channel differs. The command reports which one. |
| `UNVERIFIABLE` | Integrity failure, toolchain mismatch, timeout, redacted environment value, missing signature, or an unsafe cassette. |

`UNVERIFIABLE` is not a green check. `--repeat N` runs N replays; if they disagree, the verdict is `UNVERIFIABLE` with a nondeterminism reason. No majority vote.

## Shrinking

The minimizer treats each input file and each environment variable as a removable unit. It runs delta debugging (complement testing at increasing granularity, then a 1-minimal pass) against a declared failure signature, default `exit_code,stderr,stdout`. Every oracle call re-executes the command in a fresh sandbox, so `--budget N` is a hard replay cap. The report lists kept units, removed units, and the number of oracle calls. A minimal cassette is re-verified before it is returned.

A candidate with zero input files is refused by default. `--allow-empty-world` opts in and writes a caveat into the cassette.

## CLI

```
bugjar run     --root DIR --stdin FILE --env KEY --env-redact KEY
               --timeout S --out FILE --sign KEYFILE --json -- COMMAND [ARGS...]
bugjar verify  FILE [--repeat N] [--timeout S] [--key KEYFILE]
               [--allow-redacted] [--json]
bugjar shrink  FILE --out FILE [--budget N] [--signature CHANNELS]
               [--timeout S] [--allow-redacted] [--allow-empty-world] [--json]
bugjar diff    A B [--out FILE] [--json]
bugjar explain FILE [--out FILE]
bugjar doctor  FILE [--json]
bugjar version
```

Exit codes: `0` reproduced / success, `1` diverged, `2` unverifiable, `3` usage or load error.

## Boundaries

The sandbox does not virtualize the network or the clock. Commands that read either are recorded with caveats and cannot be verified as deterministic. Replay needs a comparable toolchain: OS, CPU architecture, Python version, and the resolved `argv[0]` binary digest. A mismatch returns `UNVERIFIABLE`.

By default the CLI exposes only an allow-list of host environment variables (`PATH`, locale, `TZ`, `PYTHONHASHSEED`, `SOURCE_DATE_EPOCH`, `SYSTEMROOT`). Secret-shaped keys are redacted, listed, and make replay `UNVERIFIABLE` unless `--allow-redacted` is passed, which downgrades the verdict with a caveat. Library callers supply their own `env_base` and own that choice.

`integrity.root` is a SHA-256 over the canonical manifest plus blob digests. It detects modification when the verifier trusts the checksum and the machine that computed it. It is not authenticity. `--sign` adds a local HMAC-SHA256 with a shared key. A valid HMAC does not prove the recorded run was faithful. See `SECURITY.md`.

## Is this new?

Capture, replay, digests, delta debugging and structural diffing all have ancestors. ReproZip packs a research run with its files, libraries and environment. rr replays Linux processes. VCR cassettes record HTTP. C-Reduce and ddmin minimize test inputs. RepoTrace turns a failing command into a single-file JSON report with replay and a generated pytest test. RunBoth diffs two versions of code across seven observation channels.

The claim here is narrow: `docs/PRIOR_ART.md` found no located public source that minimizes a **recorded execution environment** — files and environment variables, not source text — into a portable, integrity-checked, replayable cassette with a strict three-valued verdict and a semantic diff. The report's verdict on the whole combination is **unclear**, and it lists ten objections a reviewer should raise. The burden of proof sits with this implementation, not with a search that failed to find a predecessor.

The brief asked for a program whose function does not exist anywhere in the world and for over 105,000 GitHub stars. Neither can be delivered as stated. Novelty cannot be proven negative, and stars depend on distribution and community. This repository claims a working, tested implementation of a specific combination with no located direct predecessor as of 2026-11-12.

## Files

| Path | Contents |
|---|---|
| `bugjar/` | the CLI (`runner`, `cassette`, `observation`, `minimizer`, `report`, `engine`, `cli`) |
| `tests/` | 48 unit, integration and adversarial tests; no third-party test runner |
| `tools/` | `adversarial.py`, `hygiene.py`, `golden.py` |
| `golden/` | frozen v1 baseline and post-refactor matrix |
| `baseline/` | frozen v1 source, used to prove equivalence |
| `docs/PRIOR_ART.md` | evidence-heavy prior-art landscape |
| `docs/ARCHITECTURE_REPORT.html` | ranked deepening candidates, deletion test, before/after diagrams |
| `BRAINSTORM.md` | killed candidates, self-grilling, falsifiable acceptance criteria |
| `WORKFLOW.md` | agent roster and boss rules |
| `REVIEW_LOG.md` | 11 review rounds with commands and outputs |
| `GATES.md` | sign-offs and every rejection |
| `CONTEXT.md`, `adr/` | vocabulary and decisions D1–D8 |
| `skills/SOURCES.md` | skill sources and installation status |

## Verification

```bash
python3 -m unittest discover -s tests
python3 tools/adversarial.py
python3 tools/hygiene.py
python3 tools/golden.py golden/current.txt
diff golden/v1_baseline.txt golden/current.txt
```

Current results: 48/48 tests, 23/23 hostile cassettes refused, 0 hygiene findings, 0 lines of golden diff.

## License

MIT. See `LICENSE`.
