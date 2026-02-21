---
name: repo-intake
description: >
  Rapidly map a repository before implementation work. Use when starting in an unfamiliar codebase, scoping a change, or diagnosing where to edit and test. Do not use when file targets and workflow are already known and coding can start immediately.
---

# Repo Intake

## Intent

Establish a reliable working map of architecture, constraints, key modules, and verification entry points so implementation starts with minimal guesswork.

## Inputs

- User request and expected outcome.
- Project root with docs and source directories.
- Available local tooling (`rg`, test runners, build commands).

## Workflow

1. Capture goal and constraints in one sentence each.
2. Read top-level docs first (`README.md`, `ARCHITECTURE.md`, `SPEC.md`, `AGENTS.md` if present).
3. Inventory the code layout with `rg --files` and directory listing.
4. Identify execution and verification commands (`make`, test runner, lint/typecheck commands).
5. Locate likely edit points using symbol and path search.
6. Produce a short implementation map: files to touch, tests to run, and risks.

## Commands

- `ls -la`
- `rg --files`
- `rg "<symbol-or-keyword>"`
- `make -n` or project-specific task listing where available.

## Checks

- Clear map of where behavior lives and where tests should be added/updated.
- Known constraints and do-not-touch areas called out before coding.
- Verification commands identified before edits begin.

## Failure Modes + Recovery

- Documentation drift: verify assumptions against current source code.
- Multiple candidate modules: choose the smallest change surface and confirm with tests.
- No obvious tests: identify nearest comparable test and define minimal new harness.

## Examples

- Should trigger: "Map this repo and tell me where to add event retention logic."
- Should trigger: "I just cloned this project, find the safest place to add a new API endpoint."
- Should not trigger: "Update this single known function in `backend/app/main.py`."
