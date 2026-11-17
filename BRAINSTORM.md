# Brainstorm: what to build

Date: 2026-11-12. Method: superpowers `brainstorming` (explore alternatives before code), mattpocock `grilling` (one hard question at a time, recommended answer attached, no work until the question is answered), `stop-slop` (plain prose, no throat-clearing).

The brief demanded a program whose function does not exist anywhere in the world. I could not verify that claim, and I will not pretend to. Everything has ancestors. What I can defend is narrower: a specific combination with no located direct predecessor, plus an implementation that proves the combination works. This document records the kill list, the grilling, and the exact claim we are allowed to make.

## 1. Candidate ideas and why five died

| # | Idea | Killed by | Evidence |
|---|---|---|---|
| 1 | AI-slop detector for code | Prose slop detection is already a skill (`stop-slop`, 41 anti-patterns); code-quality linters are a crowded field | [citation:15] |
| 2 | Behaviour diff between two versions of a library, so an AI refactor cannot silently change behaviour | `runboth/runboth` already runs both versions, generates inputs, compares seven channels, and returns changed / no_change / abstained | [citation:11] |
| 3 | Pack a run with its files, libs and env into a portable bundle for replay | ReproZip / reprounzip has done exactly this since 2013, including `.rpz` bundles and Docker/Vagrant unpackers | [citation:7] |
| 4 | Single-file JSON bug report with replay and a generated regression test | RepoTrace already saves argv, exit code, stdout/stderr, cwd, interpreter metadata, replays, renders Markdown and emits pytest tests | [citation:37] |
| 5 | OS-level record-and-replay debugger | `rr` records full Linux execution and replays it deterministically | [citation:9] |
| 6 | LLM privacy proxy that redacts PII before egress | Adjacent commercial and OSS work exists; the wedge is not a gap | research report, §6 |

Adjacent but partial: VCR cassettes only cover HTTP [citation:8]; asciinema only covers the terminal; C-Reduce / ddmin minimize a source file or a single test input, not a recorded runtime environment [citation:32][citation:35]; in-toto / Sigstore / SLSA cover provenance, not replay equivalence; Langfuse / LangSmith / AgentOps cover agent traces, not hermetic command replay; diffoscope covers structural diff, not a verified seven-channel replay comparator.

## 2. The idea that survived

**bugjar** — put a failing command in a jar.

One command freezes an arbitrary command's input world (files, filtered env, stdin, argv, toolchain fingerprints) and its output world (exit code, stdout, stderr, created / modified / deleted files) into one portable `.bugjar` cassette. A second command replays it in a restored sandbox and returns one of exactly three verdicts: `REPRODUCED`, `DIVERGED`, `UNVERIFIABLE`. A third command **shrinks the recorded environment** — ddmin over files and environment variables — to the smallest set that still produces the original failure signature, and emits a minimal cassette with a cost report. Two cassettes can be diffed; any cassette can be explained as an evidence-linked Markdown report.

The wedge is capability 3 combined with 1 and 2. The prior-art report says this plainly: no located source describes automatic minimization of a *recorded execution environment* into a portable, integrity-checked, replayable cassette with a strict three-valued verdict; it also says the verdict on the whole is **unclear**, and the burden of proof is on the implementation (see `docs/PRIOR_ART.md`, §5 and §8).

Three design consequences were forced by that report, not invented afterwards:

- Minimizing changes the artifact that produced the observation. So a shrunk cassette is a **new cassette with its own recorded observation**, and the shrink report states the relationship to the original explicitly. We never compare a minimized cassette against the original's observation and call that equal.
- A locally stored digest is integrity, not authenticity. We say "integrity-checked", not "tamper-proof", and optional HMAC signing is a separate, explicitly weaker-than-signature claim.
- A checksum match is not `REPRODUCED`. If the toolchain, limits, redaction state or platform make comparison impossible, the answer is `UNVERIFIABLE` with a reason. Never a green check by default.

## 3. Grilling (self-administered, hostile)

**Q: Is this just ReproZip plus C-Reduce glued together?**
Recommended answer: yes, ancestrally. The difference is the unit of reduction (environment configuration, not source text), the oracle (a declared multi-channel failure signature, not a compiler exit code), and the output contract (one integrity-checked cassette with a three-valued verdict and a cost report). That is an integration claim. Do not call it an invention. If a reviewer finds a tool doing all four, we retract the claim.

**Q: Can you honestly say "the function does not exist in the world already"?**
Recommended answer: no. Capture, replay, ddmin, digests and diffing all exist. The defensible sentence is "no located direct predecessor for this combination as of 2026-11-12; verdict unclear". Say that in the README, not a marketing superlative. The brief's literal requirement is not satisfiable and is recorded here as not met.

**Q: Why would anyone star this? 105k is absurd.**
Recommended answer: stars are an aspiration, not a property of code; nothing here guarantees them. The plausible pull is that irreproducible bug reports are the most expensive routine cost in open-source triage, and AI coding agents now generate more bug reports than humans do. One command that produces a shareable, shrinkable, replayable artifact with a machine-readable verdict is a real wedge. A 105k-star outcome depends on distribution, timing and community, none of which we control. Do not put "105k" in the README as a promise.

**Q: Replay needs the same toolchain. Is the whole thing a lie?**
Recommended answer: no, but it is bounded. We record an execution profile (OS, machine, interpreter, resolved executable digest, locale, limits availability) and require comparability. A mismatch yields `UNVERIFIABLE`, not a false success. We normalize what we can control (`PYTHONHASHSEED`, `TZ`, `LC_ALL`, `PYTHONIOENCODING`) on both the capture run and the replay run.

**Q: What if the command reads the network or the clock?**
Recommended answer: out of scope, and reported. The sandbox does not virtualize the network or the clock. `UNVERIFIABLE` plus a caveat list is the honest output; the tool must never claim determinism it cannot deliver. `--repeat N` exposes nondeterminism instead of hiding it behind one lucky replay.

**Q: What is the smallest thing that would make this useless?**
Recommended answer: minimization that is slow, wrong, or silently changes the failure. Mitigations: a hard replay budget, per-run timeout, a fixed failure signature, a reported search cost, and a rule that a shrunk cassette must re-verify before it is written.

**Q: What are you going to fake?**
Recommended answer: nothing. No stubs shipped as features, no invented test results, no "8 rounds reviewed" without a command and an output per round, no claim that a skill was installed when only its public description was retrieved. Log the rejections too.

## 4. Falsifiable acceptance criteria

1. `bugjar run`, `verify`, `shrink`, `diff`, `explain`, `doctor` all work end to end on this machine with zero third-party runtime dependencies.
2. A deliberately corrupted cassette byte fails integrity and yields `UNVERIFIABLE` with the name of the failing member.
3. A command whose input file is edited between capture and verification yields `DIVERGED` with the exact differing channel.
4. Shrinking a run with 8 irrelevant files and 1 relevant file removes the 8, keeps the 1, and re-verifies the minimal cassette.
5. A cassette containing a zip-slip path, a symlink member, an absolute path, or an oversized blob is rejected at load time without writing anything outside the sandbox.
6. Secret-shaped environment variables are redacted, listed, and force `UNVERIFIABLE` on replay if the command depended on them.
7. Every review round in `REVIEW_LOG.md` has a real command and real output; every rejection in `GATES.md` names the file and the defect.
8. After the architecture refactor, the golden behavior matrix is byte-identical to the frozen baseline. No behavior changes, no new features.

## 5. Non-goals

No ptrace, no containers, no network virtualization, no cryptographic signatures over real-world identity, no claim of cross-platform bit-for-bit replay, no telemetry, no cloud service, no LLM call inside the program. The tool is a local, offline, stdlib-only CLI.
