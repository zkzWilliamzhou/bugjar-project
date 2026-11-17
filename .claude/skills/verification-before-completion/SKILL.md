---
name: verification-before-completion
description: Use before claiming anything is done, fixed, passing, or reviewed. Requires running the verification command and confirming the output first. Local adaptation of obra/superpowers; not a verbatim upstream file.
---
# Verification before completion

- No "done" without a command and its output in the log.
- No "8 rounds reviewed" without eight numbered entries, each with a distinct command and result.
- No "no regressions" without a comparison against a frozen baseline.
- No "secure" without the adversarial suite output.
- If a check cannot be run, say so and downgrade the claim. Evidence before assertions, always.
