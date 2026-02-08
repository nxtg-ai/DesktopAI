import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ui_artifacts_summary.py"


def _write_session(artifacts_root: Path, kinds: list[str], session_id: str = "session-a") -> None:
    telemetry_dir = artifacts_root / "telemetry"
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    session_file = telemetry_dir / f"{session_id}.jsonl"
    lines = []
    for idx, kind in enumerate(kinds):
        payload = {
            "session_id": session_id,
            "kind": kind,
            "message": f"event-{idx}",
            "timestamp": f"2026-02-07T00:00:0{idx}Z",
            "data": {},
        }
        lines.append(json.dumps(payload))
    session_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_summary(
    artifacts_root: Path,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--artifacts-root",
            str(artifacts_root),
            *args,
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_ui_artifacts_summary_required_kinds_file_passes(tmp_path: Path):
    artifacts_root = tmp_path / "artifacts"
    _write_session(artifacts_root, ["ui_boot", "ws_open", "event_stream_received"])

    required = tmp_path / "required.json"
    required.write_text(
        json.dumps({"required_kinds": ["ui_boot", "event_stream_received"]}),
        encoding="utf-8",
    )

    result = _run_summary(artifacts_root, "--required-kinds-file", str(required))

    assert result.returncode == 0
    assert "Missing required telemetry kinds" not in result.stdout


def test_ui_artifacts_summary_required_kinds_file_missing_kind_fails(tmp_path: Path):
    artifacts_root = tmp_path / "artifacts"
    _write_session(artifacts_root, ["ui_boot", "ws_open"])

    required = tmp_path / "required.json"
    required.write_text(
        json.dumps({"required_kinds": ["ui_boot", "event_stream_received"]}),
        encoding="utf-8",
    )

    result = _run_summary(artifacts_root, "--required-kinds-file", str(required))

    assert result.returncode == 2
    assert "Missing required telemetry kinds:" in result.stdout
    assert "- event_stream_received" in result.stdout


def test_ui_artifacts_summary_invalid_required_kinds_file_fails(tmp_path: Path):
    artifacts_root = tmp_path / "artifacts"
    _write_session(artifacts_root, ["ui_boot"])

    required = tmp_path / "required.json"
    required.write_text('{"required_kinds":"not-a-list"}', encoding="utf-8")

    result = _run_summary(artifacts_root, "--required-kinds-file", str(required))

    assert result.returncode == 5
    assert "invalid required kinds file:" in result.stdout


def test_ui_artifacts_summary_scan_recent_sessions_uses_matching_non_latest_session(tmp_path: Path):
    artifacts_root = tmp_path / "artifacts"
    _write_session(artifacts_root, ["ui_boot", "ws_open", "event_stream_received"], session_id="older-good")
    _write_session(artifacts_root, ["ui_boot"], session_id="newer-bad")

    required = tmp_path / "required.json"
    required.write_text(
        json.dumps({"required_kinds": ["ui_boot", "event_stream_received"]}),
        encoding="utf-8",
    )

    # Force "newer-bad" to be newest to validate scan fallback behavior.
    newer = artifacts_root / "telemetry" / "newer-bad.jsonl"
    newer.touch()

    result = _run_summary(
        artifacts_root,
        "--required-kinds-file",
        str(required),
        "--scan-latest-sessions",
        "2",
    )
    assert result.returncode == 0
    assert "Selected telemetry session for gate:" in result.stdout
    assert "older-good.jsonl" in result.stdout


def test_ui_artifacts_summary_session_id_file_targets_exact_session(tmp_path: Path):
    artifacts_root = tmp_path / "artifacts"
    _write_session(artifacts_root, ["ui_boot", "ws_open"], session_id="latest-bad")
    _write_session(
        artifacts_root,
        ["ui_boot", "ws_open", "event_stream_received"],
        session_id="target-good",
    )
    # Ensure latest-bad is newest so selection must come from session id file.
    (artifacts_root / "telemetry" / "latest-bad.jsonl").touch()

    required = tmp_path / "required.json"
    required.write_text(
        json.dumps({"required_kinds": ["ui_boot", "event_stream_received"]}),
        encoding="utf-8",
    )
    session_id_file = tmp_path / "session.txt"
    session_id_file.write_text("target-good\n", encoding="utf-8")

    result = _run_summary(
        artifacts_root,
        "--required-kinds-file",
        str(required),
        "--session-id-file",
        str(session_id_file),
    )
    assert result.returncode == 0
    assert "Selected telemetry session for gate:" in result.stdout
    assert "target-good.jsonl" in result.stdout


def test_ui_artifacts_summary_session_id_file_missing_fails(tmp_path: Path):
    artifacts_root = tmp_path / "artifacts"
    _write_session(artifacts_root, ["ui_boot"], session_id="any-session")

    result = _run_summary(
        artifacts_root,
        "--session-id-file",
        str(tmp_path / "missing-session-id.txt"),
    )
    assert result.returncode == 6
    assert "session id file not found:" in result.stdout


def test_ui_artifacts_summary_session_id_file_empty_fails(tmp_path: Path):
    artifacts_root = tmp_path / "artifacts"
    _write_session(artifacts_root, ["ui_boot"], session_id="any-session")

    session_id_file = tmp_path / "session-id.txt"
    session_id_file.write_text("\n", encoding="utf-8")

    result = _run_summary(
        artifacts_root,
        "--session-id-file",
        str(session_id_file),
    )
    assert result.returncode == 7
    assert "session id file is empty:" in result.stdout
