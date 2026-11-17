# Workflow and agent roster

The boss is the manager, not a contributor with a vote. Every agent delivers an artifact; the boss inspects the artifact against the acceptance criteria and either signs off or sends it back. "Looks fine" is not a sign-off. A sign-off requires a command whose output is pasted into `GATES.md`.

## Agents

| ID | Role | Input | Output | Acceptance gate |
|---|---|---|---|---|
| A1 | Prior-Art Researcher | the four claimed capabilities | `docs/PRIOR_ART.md` | cites primary sources; states closest tool; states a blunt verdict; lists skeptic objections; admits coverage limits |
| A2 | Griller / Brainstormer | brief + A1 | `BRAINSTORM.md` | at least 5 candidates killed with evidence; at least 6 hostile self-questions; falsifiable criteria; explicit statement of what could not be delivered |
| A3 | Architect | `BRAINSTORM.md` | `PLAN.md`, `CONTEXT.md`, `adr/0001-*.md` | module boundaries, cassette schema, verdict semantics, security boundary, test strategy; no code |
| A4 | Implementer (TDD) | `PLAN.md` | `bugjar/*.py` | RED shown before GREEN; every criterion in §4 of BRAINSTORM has a test; zero third-party imports at runtime |
| A5 | Test Engineer | implementation | `tests/*`, `tools/adversarial.py` | unit + property + adversarial cases; every cassette-loading path exercised with hostile input |
| A6 | Security Auditor | implementation | findings in `REVIEW_LOG.md` | path traversal, zip slip, zip bomb, symlink, env secrets, argv injection, resource limits, TOCTOU, timeout, HMAC |
| A7 | Review Loop (boss) | everything | `REVIEW_LOG.md` rounds 1-9+, `GATES.md` | 9+ rounds, each with a distinct focus, a real command, real output, and a real diff or an honest "no defect, added hardening" |
| A8 | Architecture Refactorer | frozen baseline | `bugjar/` v2, `docs/ARCHITECTURE_REPORT.html`, `adr/0002-*.md` | deletion test applied to shallow modules; ranked candidates; before/after diagrams; CONTEXT.md and ADRs updated; golden matrix byte-identical |
| A9 | Release / Docs | final tree | `README.md`, `SECURITY.md`, `pyproject.toml`, `CHANGELOG.md`, release zip | README states the honest novelty claim and the boundaries; no unverified superlatives |

A1 runs as a research subagent. A2-A9 are role-scoped work sessions executed in this workspace with explicit deliverables and gates; the boss never accepts an artifact from a role without inspecting the files on disk.

## Sequence

```
A1 ──> A2 ──> A3 ──> [GATE: plan]
                       │
                       v
A5 (tests first, RED) ──> A4 (GREEN) ──> [GATE: implementation]
                       │
                       v
A6 + A7: round 1..9 ──> [GATE: each round, reject/redo on failure]
                       │
                       v
freeze baseline + golden matrix ──> A8 ──> [GATE: byte-identical goldens]
                       │
                       v
A9 ──> [GATE: final full test + audit] ──> release
```

## Boss rules

1. Evidence before assertions. No agent may report "done", "passing", "fixed", or "8 rounds" without a command and its output.
2. Rejection triggers: failing tests, a missing acceptance criterion, a fabricated result, a `TODO`/`pass` standing in for a feature, a claim not backed by a file, or a security finding downgraded to "not important".
3. On rejection the agent revises **its own part**; the boss does not quietly patch it. The rejection, the reason, and the rework are all logged.
4. Scope is frozen after A3. A8 may change structure only. Any behavior change in A8 is an automatic rejection.
5. The boss may not invent a review round. Each round gets a numbered log entry with the exact command run.
6. Hard budget: 2 rework cycles per gate. A third failure stops the line and is reported as unfinished rather than hidden.

## Installed / referenced skills

See `skills/SOURCES.md`. The named GitHub skill repos could not be fetched into this sandbox (no outbound GitHub access; clone returns 403). Their public descriptions and the Agent Skills spec were used to build local, clearly-labelled adaptations in `.claude/skills/`, and those adaptations are what the workflow actually follows. Nothing is claimed to be a verbatim upstream install.
