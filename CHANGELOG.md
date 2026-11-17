# Changelog

## 1.0.0 — 2026-11-12

First release. Standard library only, Python 3.9+.

- `run`, `verify`, `shrink`, `diff`, `explain`, `doctor`, `version`.
- Single-file `.bugjar` cassette: canonical manifest, content-addressed blobs, SHA-256 integrity root, optional local HMAC.
- Seven observation channels and a strict `REPRODUCED` / `DIVERGED` / `UNVERIFIABLE` verdict.
- Delta-debugging minimization of the recorded World (files and environment variables) with a hard replay budget and a re-verified minimal cassette.
- Evidence-linked Markdown explanations and semantic cassette diffs.
- 48 tests, 23 hostile-cassette cases, static hygiene scan, 34-case golden behavior matrix.
- Eleven review rounds. Six product defects fixed, three broken tests rejected, two rounds with no defect.
- Structure-only architecture refactor: `runner`, `observation`, `minimizer`, `report` extracted from `engine`. Golden matrix byte-identical to the frozen v1 baseline.

Known limits: no network or clock virtualization; replay requires a comparable toolchain; digest integrity is not authenticity; `--allow-redacted` weakens the verdict. See `SECURITY.md` and `docs/PRIOR_ART.md`.

## Not in this release

- Typed `Cassette` dataclass (deferred, ADR 0002 / D7).
- Pluggable Runner backends (rejected, D6).
- Cross-platform bit-for-bit replay claims.
- Any guarantee about GitHub stars.
