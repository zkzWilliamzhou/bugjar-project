---
name: systematic-debugging
description: Use when a test fails or behavior is unexpected. Four-phase root-cause process before any fix. Local adaptation of obra/superpowers systematic-debugging; not a verbatim upstream file.
---
# Systematic debugging

1. Reproduce. Capture the exact command and the exact output.
2. Locate. Narrow to the smallest file and function that can produce the symptom. Do not guess.
3. Hypothesis. State one falsifiable cause and the observation that would disprove it.
4. Fix, then verify. Run the failing case, the whole suite, and the adversarial suite. Paste outputs.
5. If the fix does not hold, revert it and return to phase 2. Never stack speculative patches.
