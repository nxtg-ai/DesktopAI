---
name: tdd-loop
description: >
  Implement or modify code with a tight test-driven loop in this repository. Use when a request requires behavior changes, bug fixes, refactors, or API updates that should be validated with targeted tests, lint/type checks, and smoke verification. Do not use for documentation-only edits, content writing, or purely exploratory architecture brainstorming.
---

# Tdd Loop

## Intent

Deliver working code in small diffs using Red -> Green -> Refactor with explicit anti-cheat guardrails for AI-assisted implementation.

## Inputs

- User goal and acceptance criteria.
- Existing tests and command entry points (`make backend-test`, `pytest`, etc.).
- Constraints in `AGENTS.md`, `README.md`, and project conventions.

## Workflow

1. Confirm scope and non-goals in one sentence.
2. Create a short test-case list for this change, then pick one behavior slice.
3. Add or update one failing test and prove it fails for the right reason.
4. Implement the minimal code change required for that test to pass.
5. Refactor immediately while tests stay green.
6. Repeat steps 2-5 for the next slice.
7. Run focused checks first, then broader checks for changed components.
8. Report changed files, verification commands, and residual risks.

## Guardrails

- Do not mock the component whose behavior is under test.
- Prefer assertions on externally observable behavior over implementation details.
- Add at least one negative or edge test for each new behavior.
- If requirements are exploratory or unclear, run a short spike first and then switch back to strict TDD.

## Verification

- `pytest <targeted-test-path> -q`
- `make backend-test` when backend behavior changed.
- Project lint/type checks when configured and relevant to touched code.

## Checks

- New or updated tests fail before the code fix and pass after it.
- Refactor step is executed after Green and does not break passing tests.
- No unrelated formatting churn or opportunistic refactors.
- Tests are strong enough to prevent trivial or hardcoded implementations.
- Behavior changes are documented in handoff with exact verify commands.

## Failure Modes + Recovery

- Missing tests: add the smallest deterministic harness near affected code.
- Flaky integration dependencies: isolate logic with unit tests first, then run integration smoke checks.
- Ambiguous requirements: state explicit assumptions and implement conservative behavior.

## Examples

- Should trigger: "Add a retention edge-case fix and cover it with tests."
- Should trigger: "Refactor classification logic but preserve API behavior and prove it."
- Should not trigger: "Rewrite the README onboarding section."
