---
name: code-review-gate
description: >
  Review code changes with a risk-first gate before merge or release. Use when a user asks for a review, PR readiness check, merge confidence, regression risk analysis, or missing-test assessment. Do not use for implementation-only tasks where no review of existing changes is requested.
---

# Code Review Gate

## Intent

Identify bugs, regressions, and test gaps with clear severity ranking and file-level references so teams can fix high-impact issues before merge.

## Inputs

- Changed files and diff context.
- Expected behavior, acceptance criteria, and constraints.
- Existing tests and verification commands.

## Workflow

1. Inspect changed files and infer intended behavior changes.
2. Evaluate correctness, edge cases, and error handling paths.
3. Check for behavioral regressions in public interfaces and data flow.
4. Assess security/privacy risk, data loss risk, and unsafe defaults.
5. Assess performance and reliability impact on hot paths.
6. Evaluate whether tests cover changed behavior and failure modes.
7. Produce findings ordered by severity with direct file references.

## Severity

- `critical`: High-likelihood production breakage, security exposure, or data corruption.
- `high`: Major functionality risk or likely regression without a safe fallback.
- `medium`: Correctness or maintainability issue with moderate user impact.
- `low`: Minor issue, polish, or non-blocking follow-up.

## Output Format

- Findings first, ordered by severity.
- Each finding includes path and short impact statement.
- Open questions and assumptions after findings.
- Brief change summary only after findings.
- If no findings, state that explicitly and call out residual risk or test gaps.

## Checks

- Findings are specific, reproducible, and tied to changed code.
- High-risk issues are prioritized over style nits.
- Test coverage assessment is included for every meaningful behavior change.

## Failure Modes + Recovery

- Diff too large: triage by highest-risk modules first and report partial coverage explicitly.
- Missing context: list assumptions and request only the minimal missing artifact.
- No tests available: propose smallest deterministic test to close highest risk.

## Examples

- Should trigger: "Review this PR diff and list merge blockers with severity."
- Should trigger: "Audit changed backend logic for regressions and missing tests."
- Should not trigger: "Implement a new endpoint from scratch."
