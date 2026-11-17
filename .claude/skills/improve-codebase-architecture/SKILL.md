---
name: improve-codebase-architecture
description: Use on a codebase that has grown hard to navigate or test, after behavior is frozen. Surfaces shallow modules and proposes ranked deepening refactors with before/after diagrams. Local adaptation of mattpocock/skills; not a verbatim upstream file.
---
# Improve codebase architecture

Vocabulary: module, interface, depth, seam, adapter, leverage, locality. Do not use "helper", "util", "manager", or "stuff".

1. Read git history before code. Scope the review to where change actually lands.
2. Apply the deletion test to anything suspected of being shallow: would deleting it concentrate complexity, or just move it? A module whose interface costs as much as its implementation is shallow.
3. Write a self-contained HTML report with ranked candidates. Each card: files, problem, solution, benefits, before/after diagram, and a strength of Strong / Worth exploring / Speculative.
4. Stop before implementing. Run a grilling loop on the chosen candidate. Update CONTEXT.md and ADRs as decisions crystallize.
5. Only then refactor. Structure changes are allowed; behavior changes are not. Prove equivalence against a frozen golden matrix.
6. This skill explores and designs. It does not silently rewrite the codebase.
