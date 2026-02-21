---
name: doc-refresh
description: >
  Update project documentation to match implemented behavior, architecture, and developer workflows. Use when code changes make README/spec/architecture docs stale, or when onboarding and runbook clarity must be improved. Do not use for feature implementation tasks that do not require documentation updates.
---

# Doc Refresh

## Intent

Keep documentation accurate, concise, and verifiable by grounding edits in current source code and runnable commands.

## Inputs

- Changed behavior or workflows.
- Current docs (`README.md`, `ARCHITECTURE.md`, `SPEC.md`, runbooks).
- Actual commands and paths proven in repository.

## Workflow

1. Identify docs affected by code or behavior changes.
2. Verify facts from source and current commands, not memory.
3. Update only sections impacted by the change.
4. Keep command examples copy-paste ready and environment-specific where needed.
5. Add constraints, caveats, and failure cases when relevant.
6. Ensure docs and code terminology are consistent.

## Style Rules

- Prefer concrete commands and file paths over generic prose.
- Keep sections short and scannable.
- Avoid speculative future behavior unless clearly marked as planned.

## Checks

- Every changed statement is traceable to current source or verified command output.
- Commands run as documented in the current environment.
- No stale references to removed files, endpoints, or flags.

## Failure Modes + Recovery

- Ambiguous behavior: add explicit assumptions and point to code location.
- Docs drift across files: update all canonical docs in one pass.
- Missing verification: run minimal smoke commands and include results in handoff.

## Examples

- Should trigger: "Refresh README and architecture docs after backend ingest changes."
- Should trigger: "Update onboarding steps to match current Makefile targets."
- Should not trigger: "Build a new classification endpoint."
