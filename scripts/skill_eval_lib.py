#!/usr/bin/env python3
"""Helpers for validating and scoring skill eval files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


EXPECTED_SCHEMA_VERSION = "1.0"


def load_json_file(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _ensure_dict(payload: Any, label: str, errors: List[str]) -> Dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    errors.append(f"{label}: expected object, got {type(payload).__name__}")
    return {}


def _ensure_str(value: Any, label: str, errors: List[str]) -> str:
    if isinstance(value, str) and value.strip():
        return value
    errors.append(f"{label}: expected non-empty string")
    return ""


def _ensure_bool(value: Any, label: str, errors: List[str]) -> bool:
    if isinstance(value, bool):
        return value
    errors.append(f"{label}: expected boolean")
    return False


def _ensure_list(value: Any, label: str, errors: List[str]) -> List[Any]:
    if isinstance(value, list):
        return value
    errors.append(f"{label}: expected list")
    return []


def validate_cases_payload(payload: Any, label: str = "cases") -> List[str]:
    errors: List[str] = []
    root = _ensure_dict(payload, label, errors)

    schema_version = root.get("schema_version")
    if schema_version != EXPECTED_SCHEMA_VERSION:
        errors.append(
            f"{label}.schema_version: expected {EXPECTED_SCHEMA_VERSION!r}, got {schema_version!r}"
        )

    _ensure_str(root.get("skill"), f"{label}.skill", errors)
    cases = _ensure_list(root.get("cases"), f"{label}.cases", errors)

    seen_ids = set()
    for idx, case in enumerate(cases):
        case_obj = _ensure_dict(case, f"{label}.cases[{idx}]", errors)
        case_id = _ensure_str(case_obj.get("id"), f"{label}.cases[{idx}].id", errors)
        if case_id:
            if case_id in seen_ids:
                errors.append(f"{label}.cases[{idx}].id: duplicate id {case_id!r}")
            seen_ids.add(case_id)

        _ensure_str(case_obj.get("prompt"), f"{label}.cases[{idx}].prompt", errors)
        expected = _ensure_dict(case_obj.get("expected"), f"{label}.cases[{idx}].expected", errors)
        _ensure_bool(
            expected.get("should_trigger"),
            f"{label}.cases[{idx}].expected.should_trigger",
            errors,
        )

        if "must_include" in expected:
            must_include = _ensure_list(
                expected.get("must_include"),
                f"{label}.cases[{idx}].expected.must_include",
                errors,
            )
            for m_idx, phrase in enumerate(must_include):
                _ensure_str(
                    phrase,
                    f"{label}.cases[{idx}].expected.must_include[{m_idx}]",
                    errors,
                )
        if "must_include_any" in expected:
            must_include_any = _ensure_list(
                expected.get("must_include_any"),
                f"{label}.cases[{idx}].expected.must_include_any",
                errors,
            )
            if not must_include_any:
                errors.append(
                    f"{label}.cases[{idx}].expected.must_include_any: expected at least one phrase"
                )
            for m_idx, phrase in enumerate(must_include_any):
                _ensure_str(
                    phrase,
                    f"{label}.cases[{idx}].expected.must_include_any[{m_idx}]",
                    errors,
                )
        if "must_exclude" in expected:
            must_exclude = _ensure_list(
                expected.get("must_exclude"),
                f"{label}.cases[{idx}].expected.must_exclude",
                errors,
            )
            for m_idx, phrase in enumerate(must_exclude):
                _ensure_str(
                    phrase,
                    f"{label}.cases[{idx}].expected.must_exclude[{m_idx}]",
                    errors,
                )
        if "must_include_ordered" in expected:
            must_include_ordered = _ensure_list(
                expected.get("must_include_ordered"),
                f"{label}.cases[{idx}].expected.must_include_ordered",
                errors,
            )
            if len(must_include_ordered) < 2:
                errors.append(
                    f"{label}.cases[{idx}].expected.must_include_ordered: expected at least two phrases"
                )
            for m_idx, phrase in enumerate(must_include_ordered):
                _ensure_str(
                    phrase,
                    f"{label}.cases[{idx}].expected.must_include_ordered[{m_idx}]",
                    errors,
                )

    if not cases:
        errors.append(f"{label}.cases: expected at least one case")

    return errors


def validate_results_payload(payload: Any, label: str = "results") -> List[str]:
    errors: List[str] = []
    root = _ensure_dict(payload, label, errors)

    schema_version = root.get("schema_version")
    if schema_version != EXPECTED_SCHEMA_VERSION:
        errors.append(
            f"{label}.schema_version: expected {EXPECTED_SCHEMA_VERSION!r}, got {schema_version!r}"
        )

    _ensure_str(root.get("skill"), f"{label}.skill", errors)
    results = _ensure_list(root.get("results"), f"{label}.results", errors)

    seen_ids = set()
    for idx, item in enumerate(results):
        item_obj = _ensure_dict(item, f"{label}.results[{idx}]", errors)
        case_id = _ensure_str(item_obj.get("id"), f"{label}.results[{idx}].id", errors)
        if case_id:
            if case_id in seen_ids:
                errors.append(f"{label}.results[{idx}].id: duplicate id {case_id!r}")
            seen_ids.add(case_id)

        _ensure_bool(item_obj.get("should_trigger"), f"{label}.results[{idx}].should_trigger", errors)
        _ensure_str(item_obj.get("response"), f"{label}.results[{idx}].response", errors)

    if not results:
        errors.append(f"{label}.results: expected at least one result")

    return errors


def normalize_text(text: str) -> str:
    return " ".join(text.lower().split())
