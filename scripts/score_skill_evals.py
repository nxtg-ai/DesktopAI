#!/usr/bin/env python3
"""Score skill eval results against cases."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

from skill_eval_lib import (
    EXPECTED_SCHEMA_VERSION,
    load_json_file,
    normalize_text,
    validate_cases_payload,
    validate_results_payload,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score skill eval results.")
    parser.add_argument("--cases", required=True, help="Path to eval cases.json")
    parser.add_argument("--results", required=True, help="Path to eval results.json")
    parser.add_argument(
        "--allow-extra-results",
        action="store_true",
        help="Allow result IDs not present in cases",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases_path = Path(args.cases)
    results_path = Path(args.results)

    try:
        cases_payload = load_json_file(cases_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[error] failed to parse cases JSON: {exc}", file=sys.stderr)
        return 1

    try:
        results_payload = load_json_file(results_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[error] failed to parse results JSON: {exc}", file=sys.stderr)
        return 1

    validation_errors: List[str] = []
    validation_errors.extend(validate_cases_payload(cases_payload, label=str(cases_path)))
    validation_errors.extend(validate_results_payload(results_payload, label=str(results_path)))
    if validation_errors:
        for error in validation_errors:
            print(f"[error] {error}", file=sys.stderr)
        return 1

    if cases_payload["skill"] != results_payload["skill"]:
        print(
            "[error] skill mismatch: "
            f"cases has {cases_payload['skill']!r}, results has {results_payload['skill']!r}",
            file=sys.stderr,
        )
        return 1

    case_map: Dict[str, dict] = {case["id"]: case for case in cases_payload["cases"]}
    result_map: Dict[str, dict] = {row["id"]: row for row in results_payload["results"]}

    extra_result_ids = sorted(set(result_map) - set(case_map))
    if extra_result_ids and not args.allow_extra_results:
        print(
            f"[error] results contain unknown case ids: {', '.join(extra_result_ids)}",
            file=sys.stderr,
        )
        return 1

    scored_cases = []
    passed = 0
    for case_id in case_map:
        expected = case_map[case_id]["expected"]
        result = result_map.get(case_id)
        if result is None:
            scored_cases.append(
                {
                    "id": case_id,
                    "passed": False,
                    "trigger_passed": False,
                    "include_passed": False,
                    "include_any_passed": False,
                    "exclude_passed": False,
                    "ordered_passed": False,
                    "missing_phrases": expected.get("must_include", []),
                    "missing_ordered_phrases": expected.get("must_include_ordered", []),
                    "found_excluded_phrases": [],
                    "any_group": expected.get("must_include_any", []),
                    "error": "missing result",
                }
            )
            continue

        expected_trigger = expected["should_trigger"]
        got_trigger = result["should_trigger"]
        trigger_passed = expected_trigger == got_trigger

        response_text = normalize_text(result["response"])
        missing_phrases = []
        for phrase in expected.get("must_include", []):
            if normalize_text(phrase) not in response_text:
                missing_phrases.append(phrase)
        include_passed = len(missing_phrases) == 0

        include_any_phrases = expected.get("must_include_any", [])
        include_any_passed = True
        if include_any_phrases:
            include_any_passed = any(normalize_text(phrase) in response_text for phrase in include_any_phrases)

        excluded_phrases = expected.get("must_exclude", [])
        found_excluded_phrases = []
        for phrase in excluded_phrases:
            if normalize_text(phrase) in response_text:
                found_excluded_phrases.append(phrase)
        exclude_passed = len(found_excluded_phrases) == 0

        ordered_phrases = expected.get("must_include_ordered", [])
        ordered_passed = True
        missing_ordered_phrases: List[str] = []
        if ordered_phrases:
            cursor = 0
            for phrase in ordered_phrases:
                needle = normalize_text(phrase)
                idx = response_text.find(needle, cursor)
                if idx < 0:
                    ordered_passed = False
                    missing_ordered_phrases.append(phrase)
                else:
                    cursor = idx + len(needle)

        case_passed = (
            trigger_passed
            and include_passed
            and include_any_passed
            and exclude_passed
            and ordered_passed
        )
        if case_passed:
            passed += 1

        scored_cases.append(
            {
                "id": case_id,
                "passed": case_passed,
                "trigger_passed": trigger_passed,
                "include_passed": include_passed,
                "include_any_passed": include_any_passed,
                "exclude_passed": exclude_passed,
                "ordered_passed": ordered_passed,
                "missing_phrases": missing_phrases,
                "missing_ordered_phrases": missing_ordered_phrases,
                "found_excluded_phrases": found_excluded_phrases,
                "any_group": include_any_phrases,
            }
        )

    total = len(case_map)
    summary = {
        "schema_version": EXPECTED_SCHEMA_VERSION,
        "skill": cases_payload["skill"],
        "totals": {"cases": total, "passed": passed, "failed": total - passed},
        "score": (passed / total) if total else 0.0,
        "cases": scored_cases,
    }

    print(json.dumps(summary, indent=2))
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
