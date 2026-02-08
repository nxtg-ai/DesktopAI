#!/usr/bin/env python3
"""Validate skill folders and eval case files."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

from skill_eval_lib import load_json_file, validate_cases_payload

MAX_SKILL_NAME_LENGTH = 64
ALLOWED_FRONTMATTER_KEYS = {"name", "description", "license", "allowed-tools", "metadata"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate skills and eval case files.")
    parser.add_argument(
        "--skills-root",
        default=".agents/skills",
        help="Directory containing skill folders (default: .agents/skills)",
    )
    parser.add_argument(
        "--evals-root",
        default="evals/skills",
        help="Directory containing eval case files (default: evals/skills)",
    )
    return parser.parse_args()


def _strip_matching_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_frontmatter_minimal(frontmatter_text: str, label: str, errors: List[str]) -> Dict[str, Any]:
    """Minimal YAML-like parser for the subset used in SKILL.md frontmatter."""
    data: Dict[str, Any] = {}
    lines = frontmatter_text.splitlines()
    idx = 0
    while idx < len(lines):
        raw = lines[idx]
        line = raw.rstrip()
        idx += 1
        if not line.strip():
            continue
        if line.startswith("#"):
            continue
        if line.startswith(" ") or line.startswith("\t"):
            errors.append(f"{label}: unexpected indentation at line {idx}")
            continue

        match = re.match(r"^([A-Za-z0-9_-]+):(.*)$", line)
        if not match:
            errors.append(f"{label}: invalid frontmatter line {idx}: {line!r}")
            continue

        key = match.group(1)
        raw_value = match.group(2).strip()
        if key in data:
            errors.append(f"{label}: duplicate key {key!r} in frontmatter")
            continue

        if raw_value in {">", "|", ">-", "|-"}:
            block: List[str] = []
            while idx < len(lines):
                block_line = lines[idx]
                if block_line.startswith(" ") or block_line.startswith("\t"):
                    block.append(block_line.lstrip(" \t"))
                    idx += 1
                    continue
                if not block_line.strip():
                    block.append("")
                    idx += 1
                    continue
                break
            data[key] = "\n".join(block).strip()
            continue

        if raw_value == "":
            # Preserve empty-value keys while capturing optional indented content.
            block = []
            while idx < len(lines):
                block_line = lines[idx]
                if block_line.startswith(" ") or block_line.startswith("\t"):
                    block.append(block_line.lstrip(" \t"))
                    idx += 1
                    continue
                if not block_line.strip():
                    block.append("")
                    idx += 1
                    continue
                break
            data[key] = "\n".join(block).strip() if block else ""
            continue

        value = _strip_matching_quotes(raw_value)
        # Catch common YAML list syntax that must not be accepted for description.
        if raw_value.startswith("[") and raw_value.endswith("]"):
            inner = raw_value[1:-1].strip()
            if inner:
                data[key] = [part.strip() for part in inner.split(",")]
            else:
                data[key] = []
        else:
            data[key] = value

    return data


def _extract_frontmatter(skill_md: Path, errors: List[str]) -> Dict[str, Any]:
    try:
        content = skill_md.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{skill_md}: failed to read file: {exc}")
        return {}

    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        errors.append(f"{skill_md}: no YAML frontmatter found")
        return {}

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        errors.append(f"{skill_md}: invalid frontmatter format")
        return {}

    frontmatter_text = "\n".join(lines[1:end_idx])
    return _parse_frontmatter_minimal(frontmatter_text, str(skill_md), errors)


def validate_skill_file(skill_dir: Path, errors: List[str]) -> None:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        errors.append(f"{skill_dir}: SKILL.md not found")
        return

    frontmatter = _extract_frontmatter(skill_md, errors)
    if not isinstance(frontmatter, dict) or not frontmatter:
        return

    unexpected = sorted(set(frontmatter.keys()) - ALLOWED_FRONTMATTER_KEYS)
    if unexpected:
        allowed = ", ".join(sorted(ALLOWED_FRONTMATTER_KEYS))
        keys = ", ".join(unexpected)
        errors.append(
            f"{skill_md}: unexpected frontmatter key(s): {keys}. Allowed: {allowed}"
        )

    if "name" not in frontmatter:
        errors.append(f"{skill_md}: missing 'name' in frontmatter")
    if "description" not in frontmatter:
        errors.append(f"{skill_md}: missing 'description' in frontmatter")

    name = frontmatter.get("name")
    if not isinstance(name, str):
        errors.append(
            f"{skill_md}: name must be a string, got {type(name).__name__}"
        )
    else:
        stripped_name = name.strip()
        if stripped_name:
            if not re.match(r"^[a-z0-9-]+$", stripped_name):
                errors.append(
                    f"{skill_md}: name {stripped_name!r} must be lowercase hyphen-case"
                )
            if (
                stripped_name.startswith("-")
                or stripped_name.endswith("-")
                or "--" in stripped_name
            ):
                errors.append(
                    f"{skill_md}: name {stripped_name!r} cannot start/end with hyphen or contain '--'"
                )
            if len(stripped_name) > MAX_SKILL_NAME_LENGTH:
                errors.append(
                    f"{skill_md}: name too long ({len(stripped_name)} > {MAX_SKILL_NAME_LENGTH})"
                )
            if stripped_name != skill_dir.name:
                errors.append(
                    f"{skill_md}: name {stripped_name!r} does not match folder {skill_dir.name!r}"
                )

    description = frontmatter.get("description")
    if not isinstance(description, str):
        errors.append(
            f"{skill_md}: description must be a string, got {type(description).__name__}"
        )
    else:
        stripped_description = description.strip()
        if "<" in stripped_description or ">" in stripped_description:
            errors.append(f"{skill_md}: description cannot contain angle brackets")
        if len(stripped_description) > 1024:
            errors.append(
                f"{skill_md}: description too long ({len(stripped_description)} > 1024)"
            )


def validate_cases_file(case_file: Path, errors: List[str]) -> None:
    try:
        payload = load_json_file(case_file)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{case_file}: failed to parse JSON: {exc}")
        return

    payload_errors = validate_cases_payload(payload, label=str(case_file))
    errors.extend(payload_errors)

    folder_name = case_file.parent.name
    payload_skill = payload.get("skill") if isinstance(payload, dict) else None
    if isinstance(payload_skill, str) and payload_skill != folder_name:
        errors.append(
            f"{case_file}: skill field {payload_skill!r} does not match folder name {folder_name!r}"
        )


def main() -> int:
    args = parse_args()
    skills_root = Path(args.skills_root)
    evals_root = Path(args.evals_root)

    errors: List[str] = []
    skill_names = set()
    eval_skill_names = set()

    if not skills_root.exists():
        errors.append(f"skills root not found: {skills_root}")
    else:
        for skill_dir in sorted(skills_root.iterdir()):
            if not skill_dir.is_dir():
                continue
            if not (skill_dir / "SKILL.md").exists():
                continue
            skill_names.add(skill_dir.name)
            validate_skill_file(skill_dir, errors)

    if not evals_root.exists():
        errors.append(f"evals root not found: {evals_root}")
    else:
        case_files = sorted(evals_root.glob("*/cases.json"))
        if not case_files:
            errors.append(f"no eval case files found under: {evals_root}")
        for case_file in case_files:
            eval_skill_names.add(case_file.parent.name)
            validate_cases_file(case_file, errors)

    missing_eval_skills = sorted(skill_names - eval_skill_names)
    for skill in missing_eval_skills:
        errors.append(f"missing eval cases for skill: {skill}")

    unknown_eval_skills = sorted(eval_skill_names - skill_names)
    for skill in unknown_eval_skills:
        errors.append(f"eval exists for unknown skill folder: {skill}")

    if errors:
        for error in errors:
            print(f"[error] {error}", file=sys.stderr)
        return 1

    print("Skill and eval validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
