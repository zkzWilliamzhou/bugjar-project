---
name: test-driven-development
description: Use when implementing any feature or bugfix. Enforces RED then GREEN then REFACTOR with observable evidence. Local adaptation of obra/superpowers and mattpocock/skills; not a verbatim upstream file.
---
# Test-driven development

1. Write a failing test first. Run it. Paste the failure output. This is RED.
2. Write the minimum code that makes it pass. Run the tests. Paste the output. This is GREEN.
3. Refactor only with tests green.
4. Delete code written before its test exists.
5. A test that cannot fail is not a test. A mocked result is not evidence.
6. For security properties, write the attack as a test: zip slip, traversal, oversize, injection, timeout.
