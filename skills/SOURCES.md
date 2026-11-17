# Skill sources and installation status

Requested: Anthropic skills, Matt Pocock skills, Vercel Labs skills, `stop-slop`, brainstorming skills, superpowers, plus `improve-codebase-architecture`.

## What happened

- `FindSkill` (skills marketplace) returned no matching installed candidate for these names, so none could be activated as a runtime skill.
- The sandbox has no outbound GitHub access: `git clone https://github.com/tomerose/stop-slop.git` returns 403, `raw.githubusercontent.com` times out, and CDN fetches of `SKILL.md` files were unavailable.
- Therefore no verbatim upstream `SKILL.md` could be installed. Instead, `skills/SOURCES.md` records the verified public sources, and `.claude/skills/*/SKILL.md` contains **local adaptations** distilled from those public descriptions. They are valid Agent Skills documents (YAML frontmatter + instructions) and they are the methodology this project actually follows. They are not copies of upstream files and must not be represented as such.

## Verified sources

| Repo / spec | What it provides here | Source |
|---|---|---|
| `anthropics/skills` | Agent Skills spec: folder with `SKILL.md`, `name` + `description` frontmatter, progressive disclosure | https://github.com/anthropics/skills , https://agentskills.io/specification [citation:1][citation:34] |
| `mattpocock/skills` | `grilling` (relentless one-question-at-a-time interview, recommended answer attached), `grill-with-docs`, `tdd`, `improve-codebase-architecture` (deletion test for shallow modules, ranked HTML report, grilling loop, CONTEXT.md + ADRs) | https://github.com/mattpocock/skills [citation:6][citation:13][citation:24] |
| `obra/superpowers` | `brainstorming`, `writing-plans`, `executing-plans`, `test-driven-development`, `systematic-debugging`, `verification-before-completion`, `requesting-code-review`, `dispatching-parallel-agents`, `subagent-driven-development`; philosophy "evidence over claims" | https://github.com/obra/superpowers [citation:5][citation:27] |
| `vercel-labs/skills` | `npx skills add <repo>` CLI, project-scope install into `.claude/skills/`, `--skill`, `--list`, `--copy` | https://github.com/vercel-labs/skills [citation:25][citation:30] |
| `vercel-labs/agent-skills` | official skill collection, installable with `npx skills add vercel-labs/agent-skills` | [citation:31] |
| `tomerose/stop-slop` | 41 AI-writing anti-patterns; 5-dimension scoring; banned throat-clearing, binary contrasts, adverbs, false agency | https://github.com/tomerose/stop-slop [citation:4][citation:15] |
| `improve-codebase-architecture` | shipped in `mattpocock/skills`; used for the post-review refactor | [citation:6] |

## How to really install them on a machine with GitHub access

```bash
npx skills add anthropics/skills --skill '*' -a claude-code -y
npx skills add mattpocock/skills --skill '*' -a claude-code -y
npx skills add vercel-labs/agent-skills --skill '*' -a claude-code -y
npx skills add obra/superpowers --skill '*' -a claude-code -y
git clone https://github.com/tomerose/stop-slop.git .claude/skills/stop-slop
```

Read every `SKILL.md` before installing; skills are instructions that run with the agent's permissions.
