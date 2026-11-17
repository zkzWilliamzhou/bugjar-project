# Boss gates and rejections

The boss inspects artifacts on disk. "Looks fine" is not a sign-off. Every sign-off below has a command and an output in `REVIEW_LOG.md`. Rejections name the owning role, the file, and the defect. Rework budget: 2 cycles per gate; no gate needed a third.

| Gate | Owner | Artifact | Decision | Evidence |
|---|---|---|---|---|
| G0 | A1 Prior-Art Researcher | `docs/PRIOR_ART.md` | **SIGNED OFF** | 236 lines; primary-source table; closest tool named (ReproZip); verdict `unclear`; 10 skeptic objections; coverage limits stated |
| G0b | A2 Griller / Brainstormer | `BRAINSTORM.md` | **SIGNED OFF with one unmet requirement** | 6 killed candidates with citations, 7 hostile self-questions, falsifiable criteria. The brief's literal "function does not exist in the world already" is recorded as **not satisfiable** and replaced with a defensible integration claim |
| G1 | A3 Architect | `PLAN.md`, `CONTEXT.md`, `adr/0001` | **SIGNED OFF** | frozen schema, seven channels, three-valued verdict, security boundary, test strategy |
| G2 | A5 Test Engineer | `tests/*` | **REJECTED → REWORK → SIGNED OFF** | RED observed (`FAILED (failures=5, errors=3)`), then 48 tests. Broken scanner (round 1), faked encrypted attack (round 2), broken golden harness (round 10) each sent back to A5 |
| G3 | A4 Implementer | `bugjar/*.py` | **REJECTED 4× → REWORK → SIGNED OFF** | rounds 4b (relative argv0), 5 (false-minimal), 8 (unloadable cassette), 6 (lost caveats). Each revised its own part; boss did not patch silently |
| G4 | A6 Security Auditor | `REVIEW_LOG.md` findings | **SIGNED OFF with findings** | rounds 6, 7; 23/23 hostile cassettes refused; no network/eval/pickle/shell; secret scan clean |
| G5 | A7 Review Loop | `REVIEW_LOG.md` | **SIGNED OFF** | 11 numbered rounds, each with a distinct command and pasted output. No invented rounds |
| G6 | A8 Architecture Refactorer | `docs/ARCHITECTURE_REPORT.html`, `adr/0002`, `CONTEXT.md` | **SIGNED OFF under hard constraint** | deletion test applied; 3 ranked candidates with strengths; inline SVG before/after; grilling loop; D5–D8 recorded. Behavior-change rule: automatic rejection. Golden diff: 0 lines |
| G7 | A9 Release / Docs | `README.md`, `SECURITY.md`, `pyproject.toml`, `CHANGELOG.md`, release zip | **SIGNED OFF** | honest novelty claim, explicit boundaries, no star count as promise, full final audit |

## Explicit rejections

1. **Round 1 — A5**: `tools/hygiene.py` flagged the string `"...<truncated>"` as a stub. Low-quality scanner. Reworked to AST-level detection.
2. **Round 2 — A5**: `encrypted_attack` never set the encryption bit; `zipfile` resets `ZipInfo.flag_bits` on write. A faked attack reported as a product bug. Reworked to byte-patch zip headers.
3. **Round 4b — A4**: relative `argv[0]` gave an all-zero toolchain digest. Reworked with `shutil.which` + `realpath` and an `UNVERIFIABLE` short-circuit.
4. **Round 5 — A4**: ddmin could emit a zero-input cassette. Reworked with `allow_empty_world=False` plus a caveat.
5. **Round 6 — A4/A6**: a child killed by a signal was recorded with no caveat. Reworked so `ExecResult` carries runner caveats into the manifest.
6. **Round 7 — A6**: directory-mode blob member accepted. Reworked `cassette.load` to require regular-file mode.
7. **Round 8 — A4**: union of deleted inputs and produced files could exceed the loader's cap, producing an unloadable cassette. Reworked with `MAX_BLOBS_TOTAL` and sandbox discard on refusal.
8. **Round 9 — A9**: `--repeat 0` silently coerced to 1. Reworked with explicit validation.
9. **Round 10 — A5**: `Path.write_bytes(encoding=...)` crashed the harness; markdown roots unscrubbed; byte-flip corruption was layout-dependent and nondeterministic. Reworked all three.

## What the boss did not accept

- No "8 rounds reviewed" without 11 numbered rounds, each with a command.
- No "no regressions" without `diff golden/v1_baseline.txt golden/v2_current.txt` → 0 lines.
- No "secure" without `23/23 hostile cassettes refused`.
- No claim that the GitHub skills were installed verbatim. `skills/SOURCES.md` records that outbound GitHub is blocked (clone returns 403) and that `.claude/skills/*` are clearly-labelled local adaptations.
- No claim that the program's function is unique in the world. `docs/PRIOR_ART.md` says the integrated-novelty verdict is **unclear** and the burden remains on the implementation.
- No claim of 105k stars. Stars are an aspiration, not a property of code.
