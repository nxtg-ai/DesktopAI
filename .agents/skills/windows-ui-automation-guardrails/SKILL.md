---
name: windows-ui-automation-guardrails
description: >
  Plan and execute Windows desktop automation tasks with safety controls, rollback, and explicit environment boundaries. Use when requests involve UI actions such as opening apps, clicking elements, typing, shortcuts, or submitting forms. Do not use for backend-only coding tasks or passive analysis that does not perform desktop actions.
---

# Windows Ui Automation Guardrails

## Intent

Prevent unsafe or brittle automation by enforcing a preflight checklist, action constraints, and recovery paths before interacting with the Windows desktop.

## Inputs

- User objective and success criteria.
- Environment details: what runs on Windows vs WSL/Linux.
- Allowed applications, accounts, and data scope.

## Preflight Checklist

1. Define exact target app and account context.
2. Confirm sensitive actions and irreversible steps.
3. Define stop conditions and rollback path.
4. Verify focus strategy and element fallback selectors.
5. Set operation timeout and retry limits.

## Execution Workflow

1. Capture current desktop state before action.
2. Perform one atomic UI action at a time.
3. Verify expected state transition after every action.
4. On mismatch, attempt one bounded recovery action.
5. Abort and report context if recovery fails.

## Guardrails

- Never perform irreversible sends, submissions, or deletions without an explicit user checkpoint.
- Never assume element positions are stable; prefer robust selectors and active-window validation.
- Keep typed output scoped to intended fields; re-check focus before keyboard input.
- Clearly separate commands that must run on Windows from steps that can run in WSL/Linux.

## Checks

- Every action has precondition, expected result, and fallback.
- Safety checkpoint exists before any externally visible side effect.
- Final report includes action log, failures, retries, and unresolved risk.

## Failure Modes + Recovery

- Focus loss: refocus target window, re-validate active control, retry once.
- Element not found: use fallback selector strategy or application search.
- Unexpected modal dialog: stop further actions, classify modal, and request direction.

## Examples

- Should trigger: "Automate Outlook search and draft a reply with approval checks."
- Should trigger: "Create a Windows UI macro plan with rollback if the wrong window is focused."
- Should not trigger: "Optimize FastAPI event ingestion performance."
