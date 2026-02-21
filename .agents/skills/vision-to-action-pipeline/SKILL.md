---
name: vision-to-action-pipeline
description: >
  Design or refine desktop-agent pipelines that convert visual context into grounded actions with explicit state, planning, execution, and verification interfaces. Use when requests involve perception-to-action architecture, tool contracts, control loops, or reliability/safety for UI automation agents. Do not use for isolated backend bug fixes that do not involve perception or action orchestration.
---

# Vision To Action Pipeline

## Intent

Define a concrete, testable architecture for turning desktop observations into safe actions with bounded retries and measurable outcomes.

## Inputs

- Task objective and success criteria.
- Available signals (screenshot, UIA tree, active window, idle state).
- Action surface (mouse, keyboard, app intents, API side effects).

## Reference Files

- Use `references/interface-contracts.md` when defining request/response payloads between perception, grounding, planning, execution, and verification stages.
- Use `references/failure-taxonomy.md` when designing retry policies, safety stops, or runbook-level diagnostics.

## Reference Pipeline

1. Perception: ingest screenshot/UI metadata and normalize coordinates.
2. Grounding: resolve candidate targets and confidence scores.
3. Planning: choose next atomic action plus expected postcondition.
4. Execution: perform one action with timeout and retry budget.
5. Verification: compare observed state against postcondition.
6. Memory update: persist event, state diff, and decision rationale.
7. Loop control: continue, replan, or abort based on guardrails.

## Interface Contracts

- Keep stage outputs typed and versioned.
- Require explicit preconditions and postconditions for each action.
- Persist machine-readable evidence for every execution result.

## Guardrails

- Keep actions atomic and verifiable.
- Require explicit checkpoint before irreversible side effects.
- Bound retries and escalate on repeated uncertainty.
- Prefer deterministic selectors over free-form coordinate clicks.

## Checks

- Pipeline exposes clear data contracts between stages.
- Every action includes a measurable postcondition.
- Failure handling path is explicit (`replan`, `fallback`, `abort`).

## Failure Modes + Recovery

- Ambiguous target detection: lower confidence threshold is not enough; request additional evidence and re-ground.
- UI drift between versions: maintain selector fallback chain and re-verify active window.
- Action loops: enforce maximum step count and terminate with diagnostic state.

## Examples

- Should trigger: "Design a perception -> action loop for Outlook triage automation."
- Should trigger: "Define interfaces for grounding and execution verification in DesktopAI."
- Should not trigger: "Rename a backend function and update imports."
