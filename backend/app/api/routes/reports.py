import datetime

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import AppSession
from app.api.routes.ai_mode import start_run
from app.api.schemas.ai_mode import AiRunStart
from app.db.session import get_databases
from app.domain.models import Report
from app.reports.builder import build_snapshot, default_title, snapshot_markdown
from app.reports.pdf import markdown_to_pdf

router = APIRouter(prefix="/reports", tags=["reports"])


class ReportSummary(BaseModel):
    id: int
    title: str
    source: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class ReportRead(ReportSummary):
    content: str


async def _report_or_404(session: AppSession, report_id: int) -> Report:
    report = await session.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.get("", response_model=list[ReportSummary])
async def list_reports(session: AppSession) -> list[Report]:
    result = await session.execute(select(Report).order_by(Report.created_at.desc(), Report.id.desc()))
    return list(result.scalars().all())


@router.post("/snapshot", response_model=ReportRead, status_code=201)
async def create_snapshot_report(session: AppSession) -> Report:
    """A report built straight from the database; no model involved."""
    snapshot = await build_snapshot(get_databases())
    report = Report(
        title=default_title(), source="snapshot", content=snapshot_markdown(snapshot), snapshot=snapshot
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)
    return report


@router.post("/generate", status_code=202)
async def generate_ai_report(session: AppSession) -> dict[str, int]:
    """Starts a run with the reporter agent first; the report appears here when it saves it."""
    run = await start_run(
        AiRunStart(entry_agent="reporter", message="Write the network and services report."), session
    )
    return {"run_id": run.id}


@router.get("/{report_id}", response_model=ReportRead)
async def get_report(report_id: int, session: AppSession) -> Report:
    return await _report_or_404(session, report_id)


@router.get("/{report_id}/pdf")
async def get_report_pdf(report_id: int, session: AppSession) -> Response:
    report = await _report_or_404(session, report_id)
    return Response(
        markdown_to_pdf(report.title, report.content),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="report-{report.id}.pdf"'},
    )


@router.delete("/{report_id}", status_code=204)
async def delete_report(report_id: int, session: AppSession) -> None:
    await session.delete(await _report_or_404(session, report_id))
    await session.commit()


@router.delete("", status_code=204)
async def delete_all_reports(session: AppSession) -> None:
    for report in (await session.execute(select(Report))).scalars():
        await session.delete(report)
    await session.commit()
