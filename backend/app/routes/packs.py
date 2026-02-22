"""REST endpoints for ActionWorkflow Packs."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)


class GmailPdfRunRequest(BaseModel):
    days: int = 1
    output: str | None = None
    no_images: bool = False
    verbose: bool = False


def _get_pack():
    """Return the gmail_pdf_pack singleton, or raise 503 if disabled."""
    from ..deps import gmail_pdf_pack

    if gmail_pdf_pack is None:
        raise HTTPException(status_code=503, detail="Gmail PDF pack is disabled")
    if not gmail_pdf_pack.available:
        raise HTTPException(
            status_code=503,
            detail="Gmail PDF pack unavailable — script or python not found",
        )
    return gmail_pdf_pack


@router.post("/api/packs/gmail-pdf/run")
async def run_gmail_pdf(request: GmailPdfRunRequest) -> dict:
    """Trigger a Gmail PDF compilation run."""
    pack = _get_pack()
    try:
        result = await pack.run(
            days=request.days,
            output=request.output,
            no_images=request.no_images,
            verbose=request.verbose,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return result


@router.get("/api/packs/gmail-pdf/status")
async def gmail_pdf_status() -> dict:
    """Return pack availability and last run info."""
    from ..deps import gmail_pdf_pack

    if gmail_pdf_pack is None:
        return {"enabled": False, "available": False, "last_run": None}
    last = await gmail_pdf_pack.store.last_run("gmail_pdf")
    return {
        "enabled": True,
        "available": gmail_pdf_pack.available,
        "last_run": last,
    }


@router.get("/api/packs/gmail-pdf/runs")
async def gmail_pdf_runs(limit: int = Query(default=20, ge=1, le=100)) -> list[dict]:
    """List recent Gmail PDF compilation runs."""
    pack = _get_pack()
    return await pack.store.recent("gmail_pdf", limit=limit)


@router.get("/api/packs/gmail-pdf/runs/{run_id}")
async def gmail_pdf_run_detail(run_id: str) -> dict:
    """Get details of a specific run."""
    pack = _get_pack()
    run = await pack.store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
