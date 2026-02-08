#!/usr/bin/env python3
"""Batch score all skill eval results against cases."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score all skill eval results.")
    parser.add_argument(
        "--cases-root",
        default="evals/skills",
        help="Directory containing per-skill cases.json files (default: evals/skills)",
    )
    parser.add_argument(
        "--results-root",
        default="evals/results/skills",
        help="Directory containing per-skill results.json files (default: evals/results/skills)",
    )
    return parser.parse_args()


def run_single_score(cases_file: Path, results_file: Path) -> Dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/score_skill_evals.py",
        "--cases",
        str(cases_file),
        "--results",
        str(results_file),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

    if proc.returncode == 0:
        summary = json.loads(proc.stdout)
        return {
            "status": "passed",
            "summary": summary,
        }

    stderr = proc.stderr.strip()
    stdout = proc.stdout.strip()
    return {
        "status": "failed",
        "error": stderr or stdout or "unknown scoring error",
    }


def main() -> int:
    args = parse_args()
    cases_root = Path(args.cases_root)
    results_root = Path(args.results_root)

    if not cases_root.exists():
        print(f"[error] cases root not found: {cases_root}", file=sys.stderr)
        return 1
    if not results_root.exists():
        print(f"[error] results root not found: {results_root}", file=sys.stderr)
        return 1

    case_files = sorted(cases_root.glob("*/cases.json"))
    if not case_files:
        print(f"[error] no case files found under: {cases_root}", file=sys.stderr)
        return 1

    report_entries: List[Dict[str, Any]] = []
    passed = 0
    failed = 0

    for case_file in case_files:
        skill = case_file.parent.name
        results_file = results_root / skill / "results.json"
        if not results_file.exists():
            failed += 1
            report_entries.append(
                {
                    "skill": skill,
                    "status": "failed",
                    "error": f"missing results file: {results_file}",
                }
            )
            continue

        score = run_single_score(case_file, results_file)
        if score["status"] == "passed":
            passed += 1
            summary = score["summary"]
            totals = summary.get("totals", {})
            report_entries.append(
                {
                    "skill": skill,
                    "status": "passed",
                    "score": summary.get("score"),
                    "cases": totals.get("cases"),
                    "passed_cases": totals.get("passed"),
                    "failed_cases": totals.get("failed"),
                }
            )
        else:
            failed += 1
            report_entries.append(
                {
                    "skill": skill,
                    "status": "failed",
                    "error": score["error"],
                }
            )

    output = {
        "schema_version": "1.0",
        "totals": {
            "skills": len(case_files),
            "passed": passed,
            "failed": failed,
        },
        "skills": report_entries,
    }
    print(json.dumps(output, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
