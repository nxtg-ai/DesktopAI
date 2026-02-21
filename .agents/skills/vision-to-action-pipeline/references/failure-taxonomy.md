# Failure Taxonomy

Use this taxonomy to classify failures consistently and drive deterministic recovery.

## Categories

## 1) Target Ambiguity

- Signal: multiple candidates with close confidence, no unique selector.
- Typical root causes: dense UI layouts, stale OCR, repeated labels.
- Recovery:
- Request another perception frame.
- Require selector disambiguation field.
- Downgrade to no-op and replan if ambiguity persists.

## 2) Focus Mismatch

- Signal: active window or focused element differs from precondition.
- Typical root causes: popup steals focus, user interaction races, OS notifications.
- Recovery:
- Refocus intended window once.
- Re-run precondition checks.
- Abort if focus remains wrong after one retry.

## 3) Selector Drift

- Signal: selector lookup fails though element appears visually present.
- Typical root causes: app update changed AutomationId/UI tree path.
- Recovery:
- Try fallback selector chain in priority order.
- Refresh selector cache with latest stable match.
- Open maintenance task for selector set update.

## 4) Postcondition Failure

- Signal: action executes but expected state transition is not observed.
- Typical root causes: click landed on wrong element, app lag, disabled control.
- Recovery:
- Capture evidence and retry once after bounded delay.
- Re-ground target and plan alternate action.
- Abort with diagnostic state if repeated.

## 5) Timing and Latency

- Signal: timeout reached before action completion or verification.
- Typical root causes: heavy UI rendering, network stalls, background load.
- Recovery:
- Increase timeout within configured max budget.
- Use explicit wait condition rather than fixed sleep.
- Flag environment as degraded after repeated timeouts.

## 6) Irreversible Side-Effect Risk

- Signal: action would send, submit, delete, or publish externally.
- Typical root causes: missing safety gate, stale checkpoint logic.
- Recovery:
- Require explicit checkpoint token before execution.
- Re-validate target and payload immediately before action.
- Block action when checkpoint missing or expired.

## 7) Transport or Integration Failure

- Signal: backend event ingestion or control channel unavailable.
- Typical root causes: websocket drop, API timeout, schema mismatch.
- Recovery:
- Buffer action log locally with monotonic sequence ids.
- Retry transport with exponential backoff and jitter.
- Enter safe paused state after retry budget exhausted.

## Error Code Mapping

- `E_AMBIGUOUS_TARGET`: target ambiguity unresolved.
- `E_FOCUS_MISMATCH`: wrong active window or focus control.
- `E_SELECTOR_MISS`: selector lookup failure.
- `E_POSTCONDITION_FAIL`: expected state transition missing.
- `E_TIMEOUT`: action or verification timeout.
- `E_CHECKPOINT_REQUIRED`: irreversible step blocked pending confirmation.
- `E_TRANSPORT_DOWN`: event/control transport unavailable.

## Escalation Rules

- Escalate after two consecutive failures with same error code on same step.
- Escalate immediately for irreversible-side-effect checkpoints.
- Include last `PerceptionOutput`, `PlanStep`, and `ExecutionResult` references in escalation payload.
