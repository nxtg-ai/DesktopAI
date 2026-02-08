# NxtG Forge; SKILLS.md

This is the human-friendly catalog + standards for Codex skills in this repo.

## 0) What a Codex skill is (and where it lives)
A Codex skill is a folder containing a required `SKILL.md` (Markdown instructions + YAML frontmatter).
Repo-scoped skills live here:

.agents/skills/<skill-name>/SKILL.md

Skills may also include optional scripts, references, and assets:
- scripts/        (deterministic helpers)
- references/     (docs, specs)
- assets/         (templates, prompts, fixtures)

## 1) Skill design rules (hard-won defaults)
1) Keep skills small and modular.
2) Prefer instructions over scripts; only script when you need determinism or external data.
3) Assume no context. Write the skill as if Codex knows nothing beyond the user prompt + repo.
4) The YAML `description` is for the agent (routing), not for humans:
   - explicitly say WHEN to use it
   - explicitly say WHEN NOT to use it
   - vague descriptions cause over-triggering

## 2) Skill template (copy/paste)
Create a folder: `.agents/skills/<skill-name>/`
Then add `SKILL.md`:

---
name: <skill-name>
description: >
  Use when ... (be explicit). Do not use when ...
---

# <skill-name>

## Intent
One sentence; what success looks like.

## Inputs
- What you expect from the user or from the repo state.

## Steps
1. Step-by-step instructions.
2. Include exact file paths to inspect/change.
3. Include exact commands to verify.

## Checks (definition of done)
- Bullet list of objective pass/fail criteria.

## Failure modes + recovery
- What commonly goes wrong; what to try next.

## Examples
- Example prompt that SHOULD trigger this skill.
- Example prompt that should NOT trigger this skill.

## 3) Creating skills
Option A; Use the built-in Codex skill creator:
- In Codex CLI/IDE: `$skill-creator`
- Provide a short description of what you want.

Option B; Create manually:
- `mkdir -p .agents/skills/<skill-name>`
- Add `SKILL.md` using the template above.

## 4) Current repo skill catalog (starter set)
These are recommended initial skills to create (add as you implement them):

### Core engineering loop
- `tdd-loop`:
  Use when the request involves implementing or modifying code with tests and verification.
  Run Red -> Green -> Refactor with a test-case list and anti-cheat assertions.
- `code-review-gate`:
  Use when preparing for PR/merge; produce prioritized risk findings + fix suggestions.
- `release-checklist`:
  Use when tagging a release; validates versioning, changelog, build artifacts, and smoke tests.

### DesktopAI-specific workflows (optional but aligned)
- `windows-ui-automation-guardrails`:
  Use when generating any UI automation plan; requires safety checks, user approvals, and rollback steps.
- `vision-to-action-pipeline`:
  Use when designing perception -> grounding -> action execution loops; outputs a concise architecture + interfaces.

### Knowledge + docs
- `repo-intake`:
  Use when Codex needs to quickly map the repo and constraints before coding.
- `doc-refresh`:
  Use when updating README/architecture docs; enforces consistent structure and avoids fluff.

## 5) Systematic testing of skills (strongly recommended)
If a skill matters, test it:
- Create a minimal eval harness that runs the skill against canonical prompts
- Require structured JSON outputs for pass/fail gating when feasible
- Track regressions over time (CI-friendly)

Suggested pattern:
- store eval prompts + expected checks under `evals/skills/<skill-name>/`
- enforce an output schema so results are machine-scorable
- use expected checks deliberately:
  - `must_include`: all phrases must appear
  - `must_include_any`: at least one phrase must appear
  - `must_exclude`: phrases that must not appear
  - `must_include_ordered`: phrases that must appear in sequence

Repo commands:
- `make skills-validate`
- `make skills-score SKILL_CASES=evals/skills/<skill-name>/cases.json SKILL_RESULTS=<results.json>`
- `make skills-score-all SKILL_RESULTS_ROOT=evals/results/skills`

Batch scoring input layout:
- `evals/results/skills/<skill-name>/results.json`
- CI expectation: every skill in `.agents/skills/` should have a matching `results.json` fixture.

Schemas:
- `evals/skills/schema/cases.schema.json`
- `evals/skills/schema/results.schema.json`

Local pre-commit gate:
- `pip install pre-commit`
- `pre-commit install`

## 6) AI TDD guardrails (repo default)
- Keep a short test-case list and pick one behavior slice per loop.
- Prove Red explicitly before Green.
- Refactor is mandatory after Green, not optional cleanup debt.
- Add at least one negative/edge test for each newly introduced behavior.
- Avoid brittle tests that only assert internals or mocks.
- For exploratory work, do a short spike/spec first, then return to strict TDD loops.
