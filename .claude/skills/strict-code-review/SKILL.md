---
name: strict-code-review
description: Use between tasks and before any sign-off. Reviews against the plan and reports issues by severity; critical issues block progress. Local adaptation of obra/superpowers requesting-code-review and receiving-code-review; not a verbatim upstream file.
---
# Strict code review

- Review against the frozen plan, not against taste.
- Report by severity: Critical (blocks), Major (blocks), Minor (logged), Nit (ignored).
- Critical: missing acceptance criterion, failing test, fabricated result, stub standing in for a feature, unsafe deserialization, path traversal, a security finding downgraded to "not important".
- Every finding names a file, a line and a failing command. No finding without evidence.
- Do not performatively agree with feedback. Verify the claim before changing code.
- The boss sends rejected work back to its owning role. The boss does not quietly patch it.
