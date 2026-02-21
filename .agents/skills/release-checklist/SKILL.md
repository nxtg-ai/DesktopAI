---
name: release-checklist
description: >
  Validate release readiness before tagging or publishing by checking versioning, changelog accuracy, tests, build artifacts, and rollback notes. Use when preparing a release candidate, cutting a version, or verifying a hotfix release. Do not use for regular feature development that is not entering a release process.
---

# Release Checklist

## Intent

Provide a deterministic gate for releases so teams do not ship unverified changes, missing documentation, or inconsistent version metadata.

## Inputs

- Target version and release type (`major`, `minor`, `patch`, hotfix).
- Files that carry version/changelog/release notes.
- Build, test, and smoke commands for affected components.

## Workflow

1. Confirm scope of included changes and exclusions.
2. Verify version bump aligns with release type and compatibility impact.
3. Verify changelog/release notes reflect user-visible behavior changes.
4. Run required tests and targeted smoke checks for changed surfaces.
5. Build release artifacts and confirm naming/version consistency.
6. Capture rollback strategy and known risks.
7. Produce a go/no-go summary with blocking issues listed first.

## Checklist

- Version metadata updated exactly once in canonical location.
- Changelog entry includes date, version, and key behavior changes.
- Tests for touched subsystems pass in current environment.
- Build artifacts are reproducible and include expected assets.
- Rollback path is documented and technically feasible.

## Checks

- Any blocking failure yields `no-go` status.
- Non-blocking risks are explicitly listed with owner and mitigation.
- Final output includes exact verification commands and results summary.

## Failure Modes + Recovery

- Missing changelog updates: block release until entries are complete.
- Inconsistent artifact versions: rebuild from clean state and compare metadata.
- Partial test coverage: run minimal additional targeted tests before go/no-go.

## Examples

- Should trigger: "Run a release readiness check for `v0.6.0`."
- Should trigger: "Before tagging this hotfix, verify version/changelog/tests/artifacts."
- Should not trigger: "Implement idle-event persistence improvements."
