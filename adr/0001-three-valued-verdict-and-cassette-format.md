# ADR 0001 — Three-valued verdict and cassette format

Status: accepted. Date: 2026-11-12.

## Context

Capture/replay tools (ReproZip, RepoTrace, VCR, rr) exist, but none of the located sources defines a strict comparator with a non-collapsible third state. A two-state verifier turns "I could not check" into a green check, which is the exact failure mode this program exists to avoid.

## Decision

The cassette is a ZIP containing canonical `manifest.json` plus content-addressed blobs. `integrity.root` is a SHA-256 over canonical manifest (minus root/signature) plus sorted blob digests. Verification returns exactly `REPRODUCED`, `DIVERGED`, or `UNVERIFIABLE`, each with a machine-readable reason list.

Seven channels: exit_code, stdout, stderr, created, modified, deleted, witness. Timing is deliberately excluded; `--repeat` exposes nondeterminism.

## Consequences

- Profile mismatches, redactions, timeouts, and unsafe cassettes must return `UNVERIFIABLE`. More code, fewer lies.
- Digest-only integrity means a cassette is not authenticated. Optional HMAC-SHA256 with a local key is separate and explicitly documented as weaker than a signature with a trust policy.
- Every verdict must be reproducible from the cassette alone, with no hidden host state.

## Rejected

- Majority-vote verdicts on repeated replays: hides flakiness.
- Comparing a shrunk cassette against its parent's Observation: changes the artifact and pretends it did not.
- `pickle` or YAML for the manifest: unsafe deserialization, no reason to accept the risk.
