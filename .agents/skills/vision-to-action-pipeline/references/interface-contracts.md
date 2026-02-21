# Interface Contracts

Use these contracts when implementing or reviewing perception-to-action loops.

## Contract Versioning

- Include `schema_version` on all top-level payloads.
- Treat unknown required fields as validation failures.
- Allow additive optional fields across minor revisions.

## PerceptionOutput

```json
{
  "schema_version": "1.0",
  "frame_id": "f-20260206-001",
  "timestamp": "2026-02-06T12:34:56Z",
  "active_window": {
    "title": "Inbox - Outlook",
    "process_name": "OUTLOOK.EXE",
    "is_foreground": true
  },
  "elements": [
    {
      "element_id": "el-17",
      "role": "button",
      "name": "Send",
      "bounds": [1412, 992, 1492, 1028],
      "selector": {
        "uia_path": "Window[Inbox]/Pane[Message]/Button[Send]",
        "automation_id": "SendButton"
      },
      "confidence": 0.97
    }
  ],
  "text_snippets": [
    {
      "region": [420, 200, 980, 240],
      "text": "Search mail and people",
      "confidence": 0.91
    }
  ]
}
```

## GroundingResult

```json
{
  "schema_version": "1.0",
  "frame_id": "f-20260206-001",
  "goal": "Open search box",
  "candidates": [
    {
      "candidate_id": "c-1",
      "target_ref": "el-42",
      "strategy": "uia_selector",
      "confidence": 0.94,
      "disambiguation_notes": []
    }
  ],
  "selected_candidate_id": "c-1"
}
```

## PlanStep

```json
{
  "schema_version": "1.0",
  "task_id": "task-87",
  "step_index": 3,
  "intent": "click",
  "target": {
    "candidate_id": "c-1",
    "selector_priority": ["automation_id", "uia_path", "bounds"]
  },
  "preconditions": [
    "window.process_name == OUTLOOK.EXE",
    "target.visible == true"
  ],
  "postconditions": [
    "focus.element_role == textbox",
    "focus.name contains Search"
  ],
  "timeout_ms": 3000,
  "max_retries": 1
}
```

## ExecutionResult

```json
{
  "schema_version": "1.0",
  "task_id": "task-87",
  "step_index": 3,
  "status": "success",
  "elapsed_ms": 214,
  "evidence": {
    "postcondition_checks": [
      {"name": "focus.element_role == textbox", "passed": true},
      {"name": "focus.name contains Search", "passed": true}
    ],
    "active_window_after": "Inbox - Outlook"
  },
  "error_code": null
}
```

## StateSnapshot

```json
{
  "schema_version": "1.0",
  "task_id": "task-87",
  "step_index": 3,
  "last_success": "2026-02-06T12:35:02Z",
  "confidence": 0.9,
  "blockers": [],
  "decision_trace_ref": "trace-87-3"
}
```

## Invariants

- Reject actions when `active_window.is_foreground` is false.
- Abort when preconditions fail twice in a row for the same step.
- Require at least one deterministic selector before executing input events.
- Store `ExecutionResult.evidence` for all non-noop actions.
