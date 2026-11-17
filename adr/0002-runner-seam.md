# ADR 0002 — Runner seam and deep modules

Status: accepted. Date: 2026-11-12. Supersedes nothing; amends the module layout in `PLAN.md`.

## Context

After eleven review rounds the behavior was frozen. The frozen v1 `engine.py` was 782 lines and owned five unrelated concerns: sandbox mechanics, channel semantics, delta debugging, report formatting, and orchestration. Applying the deletion test showed that removing it would concentrate complexity back into one place, but that the file itself was shallow: its interface was as large as the implementation it hid. The brief requires an architecture refactor with **no change to any function of the program**.

## Decision

Split `engine.py` into four deep modules and leave `engine.py` as orchestration:

| Module | Interface | Hides |
|---|---|---|
| `runner.py` | `execute(world, argv, env, timeout, stdin) -> ExecResult` | temp dirs, `setrlimit`, process groups, symlink skipping, snapshots, content-addressed blob collection |
| `observation.py` | `observe`, `channels`, `same`, `signature_match`, `profile`, `build_manifest` | the seven channels, normalization, toolchain comparability, manifest shape |
| `minimizer.py` | `ddmin(units, oracle) -> units` | delta debugging and the replay budget exception |
| `report.py` | `diff`, `explain`, `doctor` | flattening, volatile-field filtering, evidence citations, profile comparison |
| `engine.py` | `run`, `verify`, `shrink` | sequencing only |

`cassette.py` and `util.py` were already deep and were left alone. Three compatibility aliases (`_ddmin`, `_profile`, `_snapshot`) are retained so the review probes in `REVIEW_LOG.md` remain executable.

## Constraints

- No signature or return-value change to any public function.
- No new feature, no new CLI flag, no changed verdict, no changed output string.
- Proof: `golden/v1_baseline.txt` and `golden/v2_current.txt` must be byte-identical.
- Full unit/integration suite, adversarial suite, and hygiene scan must stay green.

## Rejected

- **Typed `Cassette` dataclass**: would change the module interface. Deferred to a later release (D7).
- **Pluggable Runner abstraction**: one implementation does not justify a seam interface; deleting it costs nothing today (D6).
- **Moving `cli.py` into a subpackage**: pure relocation, no concentration of complexity.

## Consequences

Security-sensitive code now has one address: `runner.py` owns process limits and `cassette.py` owns untrusted archive parsing. A schema change lands in `observation.py` plus `report.py` instead of one 782-line file. The cost is more files and three documented compatibility aliases.

## Verification

```
48/48 tests OK
23/23 hostile cassettes refused
hygiene: 0 findings
diff golden/v1_baseline.txt golden/v2_current.txt  ->  no differences
```
