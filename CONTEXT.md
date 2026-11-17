# CONTEXT.md — shared vocabulary

Terms are used only where a decision needs them. No term is mandated structurally.

- **World** — the input side of a run: the file tree, the environment variables, stdin, and argv that a command sees. A cassette records a World.
- **Observation** — the output side of a run, as seven comparable channels. An Observation is a value, not a process.
- **Cassette** — one portable, integrity-checked file containing a World, an Observation, a Profile and caveats.
- **Profile** — the host facts required for a replay to be comparable (OS, machine, interpreter, resolved executable digest, locale, limit availability, normalization settings).
- **Verdict** — exactly one of `REPRODUCED`, `DIVERGED`, `UNVERIFIABLE`. "Cannot check" is never folded into success.
- **Failure signature** — the subset of Observation channels that shrinking must preserve. Default `exit_code,stderr,stdout`.
- **Unit** — one removable piece of a World: one input file or one environment variable. Shrinking reduces Units, not source lines.
- **Witness** — digest of the restored World, proving a replay ran on the inputs it claims to have run on.
- **Caveat** — a known limit of the recording (skipped symlink, unsupported entry, redaction, network/clock outside the model). Caveats travel with the cassette; they never turn into a green verdict.
- **Seam** — the boundary where a Runner can be swapped without changing the World/Observation contract. In v2 the seam is the `runner` module: one `execute()` call, one `ExecResult` back.
- **Deep module** — a module whose interface is much smaller than the implementation it hides. Passing the deletion test: removing it would concentrate complexity rather than merely move it.
- **Golden matrix** — 34 scrubbed CLI transcripts (1,182 lines) frozen from v1. Used to prove that a structure-only refactor changed no function.

## Decisions

- D1 (2026-11-12): three-valued verdict, no majority vote on `--repeat`; split results are `UNVERIFIABLE`.
- D2 (2026-11-12): a shrunk cassette is a new cassette with its own Observation; it is never compared against the parent's Observation and declared equal.
- D3 (2026-11-12): "integrity-checked" is the only integrity claim; authenticity requires optional HMAC and is labeled separately.
- D4 (2026-11-12): no network or clock virtualization; these are caveats, not features.
- D5 (2026-11-12, architecture): `engine.py` was shallow — five unrelated change drivers in one file. Split into `runner`, `observation`, `minimizer`, `report`; `engine` is orchestration only.
- D6 (2026-11-12, architecture): rejected a pluggable Runner abstraction. One implementation does not justify an interface; deleting the abstraction would cost nothing.
- D7 (2026-11-12, architecture): deferred a typed `Cassette` object. It changes the module interface, which the brief forbids for this release.
- D8 (2026-11-12, architecture): behavior equivalence is proven by a byte-identical golden diff, not by a claim. Any behavior change in the refactor is an automatic rejection.
