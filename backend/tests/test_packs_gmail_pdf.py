"""Tests for the Gmail PDF pack — store, pack, routes, and chat routing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from packs.gmail_pdf import GmailPdfPack, PackRunStore

# ── PackRunStore ──────────────────────────────────────────────────────────


@pytest.fixture
def run_store():
    return PackRunStore(path=":memory:")


@pytest.mark.asyncio
async def test_store_start_and_finish(run_store: PackRunStore):
    run_id = await run_store.start_run("gmail_pdf", {"days": 3})
    assert run_id
    await run_store.finish_run(
        run_id, exit_code=0, status="success", output_path="/tmp/out.pdf",
    )
    run = await run_store.get_run(run_id)
    assert run is not None
    assert run["status"] == "success"
    assert run["exit_code"] == 0
    assert run["output_path"] == "/tmp/out.pdf"


@pytest.mark.asyncio
async def test_store_empty_last_run(run_store: PackRunStore):
    last = await run_store.last_run("gmail_pdf")
    assert last is None


@pytest.mark.asyncio
async def test_store_failed_run(run_store: PackRunStore):
    run_id = await run_store.start_run("gmail_pdf")
    await run_store.finish_run(run_id, exit_code=1, status="failed", stderr="boom")
    run = await run_store.get_run(run_id)
    assert run["status"] == "failed"
    assert run["stderr"] == "boom"


@pytest.mark.asyncio
async def test_store_recent_ordering(run_store: PackRunStore):
    id1 = await run_store.start_run("gmail_pdf", {"days": 1})
    await run_store.finish_run(id1, exit_code=0, status="success")
    id2 = await run_store.start_run("gmail_pdf", {"days": 2})
    await run_store.finish_run(id2, exit_code=0, status="success")
    recent = await run_store.recent("gmail_pdf", limit=10)
    assert len(recent) == 2
    # Most recent first
    assert recent[0]["run_id"] == id2
    assert recent[1]["run_id"] == id1


# ── GmailPdfPack ─────────────────────────────────────────────────────────


@pytest.fixture
def fake_script_dir(tmp_path: Path):
    """Create a minimal fake script directory."""
    script = tmp_path / "main_pdf.py"
    script.write_text("print('PDF saved to: /tmp/newsletters.pdf')")
    # Create a fake python interpreter (just needs to exist for `available` check)
    python = tmp_path / "python"
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)
    return tmp_path


@pytest.fixture
def pack(fake_script_dir: Path, run_store: PackRunStore):
    return GmailPdfPack(
        script_dir=str(fake_script_dir),
        output_dir=str(fake_script_dir / ".outputs"),
        python_path=str(fake_script_dir / "python"),
        timeout_s=30,
        store=run_store,
    )


def test_available_when_files_exist(pack: GmailPdfPack):
    assert pack.available is True


def test_unavailable_when_script_missing(tmp_path: Path, run_store: PackRunStore):
    p = GmailPdfPack(
        script_dir=str(tmp_path),
        output_dir=str(tmp_path),
        python_path=str(tmp_path / "nonexistent"),
        timeout_s=30,
        store=run_store,
    )
    assert p.available is False


@pytest.mark.asyncio
async def test_successful_run(pack: GmailPdfPack, run_store: PackRunStore):
    """Test a successful subprocess run with mocked process."""
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(
        b"Processing...\nPDF saved to: /tmp/out.pdf\nDone",
        b"",
    ))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await pack.run(days=3)

    assert result["status"] == "success"
    assert result["exit_code"] == 0
    assert result["output_path"] == "/tmp/out.pdf"
    assert result["run_id"]

    # Check it was recorded in the store
    stored = await run_store.get_run(result["run_id"])
    assert stored is not None
    assert stored["status"] == "success"


@pytest.mark.asyncio
async def test_run_records_in_store(pack: GmailPdfPack, run_store: PackRunStore):
    """After a run, the store should contain the result."""
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"done", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await pack.run(days=1)

    last = await run_store.last_run("gmail_pdf")
    assert last is not None
    assert last["run_id"] == result["run_id"]


@pytest.mark.asyncio
async def test_concurrent_run_blocked(pack: GmailPdfPack):
    """Second concurrent run should raise RuntimeError."""
    # Acquire the lock to simulate a running process
    await pack._lock.acquire()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            await pack.run(days=1)
    finally:
        pack._lock.release()


# ── API routes ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_route_status_when_disabled():
    """GET /api/packs/gmail-pdf/status returns disabled when pack is None."""
    from app.routes.packs import gmail_pdf_status

    with patch("app.routes.packs._get_pack", side_effect=None):
        with patch("app.deps.gmail_pdf_pack", None):
            resp = await gmail_pdf_status()
    assert resp["enabled"] is False
    assert resp["available"] is False


@pytest.mark.asyncio
async def test_route_run_when_disabled():
    """POST /api/packs/gmail-pdf/run returns 503 when pack is disabled."""
    from app.routes.packs import GmailPdfRunRequest, run_gmail_pdf
    from fastapi import HTTPException

    with patch("app.deps.gmail_pdf_pack", None):
        with pytest.raises(HTTPException) as exc_info:
            await run_gmail_pdf(GmailPdfRunRequest())
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_route_run_triggers_pack():
    """POST /api/packs/gmail-pdf/run calls pack.run()."""
    from app.routes.packs import GmailPdfRunRequest, run_gmail_pdf

    mock_pack = MagicMock()
    mock_pack.available = True
    mock_pack.run = AsyncMock(return_value={
        "run_id": "abc", "status": "success", "exit_code": 0,
        "output_path": "/tmp/x.pdf", "stdout": "", "stderr": "",
    })

    with patch("app.routes.packs._get_pack", return_value=mock_pack):
        result = await run_gmail_pdf(GmailPdfRunRequest(days=5))
    assert result["status"] == "success"
    mock_pack.run.assert_awaited_once_with(
        days=5, output=None, no_images=False, verbose=False,
    )


# ── Chat routing ──────────────────────────────────────────────────────────


def test_pattern_compile_newsletters():
    """'compile newsletters' should match the gmail_pdf pattern."""
    from app.routes.agent import _match_direct_pattern

    result = _match_direct_pattern("compile newsletters")
    assert result is not None
    action, params = result
    assert action == "_pack_gmail_pdf"
    assert params["days"] == 1


def test_pattern_compile_newsletters_with_days():
    """'build newsletters for 7 days' should extract days=7."""
    from app.routes.agent import _match_direct_pattern

    result = _match_direct_pattern("build newsletters for 7 days")
    assert result is not None
    action, params = result
    assert action == "_pack_gmail_pdf"
    assert params["days"] == 7


def test_pattern_compile_gmail_newsletters():
    """'compile gmail newsletters' should match."""
    from app.routes.agent import _match_direct_pattern

    result = _match_direct_pattern("compile gmail newsletters")
    assert result is not None
    assert result[0] == "_pack_gmail_pdf"


def test_pattern_run_newsletter_from_last_days():
    """'run newsletter from last 3 days' should match with days=3."""
    from app.routes.agent import _match_direct_pattern

    result = _match_direct_pattern("run newsletter from last 3 days")
    assert result is not None
    assert result[0] == "_pack_gmail_pdf"
    assert result[1]["days"] == 3


def test_multi_step_blocks_pack():
    """Gmail PDF pack cannot appear in a multi-step chain."""
    from app.routes.agent import _split_multi_command

    result = _split_multi_command("compile newsletters, open notepad")
    assert result is None


@pytest.mark.asyncio
async def test_chat_direct_pack_gmail_pdf():
    """Chat endpoint should route 'compile newsletters' through the pack handler."""
    from app.routes.agent import _try_direct_command

    mock_pack = MagicMock()
    mock_pack.available = True
    mock_pack.run = AsyncMock(return_value={
        "run_id": "r1", "status": "success", "exit_code": 0,
        "output_path": "/tmp/news.pdf", "stdout": "", "stderr": "",
    })

    with patch("app.routes.agent.gmail_pdf_pack", mock_pack, create=True):
        with patch("app.deps.gmail_pdf_pack", mock_pack):
            result = await _try_direct_command("compile newsletters")

    assert result is not None
    assert result["action"] == "_pack_gmail_pdf"
    assert "Done" in result["response"]
    assert "/tmp/news.pdf" in result["response"]
