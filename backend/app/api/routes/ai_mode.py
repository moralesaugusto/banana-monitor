
from fastapi import APIRouter, HTTPException
from sqlalchemy import delete, func, select

from app.api.deps import AppSession, CredentialServiceDep, CredentialsSession, require_credential
from app.api.schemas.ai_mode import (
    AiModeSettingsRead,
    AiModeSettingsUpdate,
    AiModeTools,
    AiRunDetail,
    AiRunStart,
    AiRunStepRead,
    AiRunSummary,
    CustomToolBase,
    CustomToolRead,
    GuardrailBase,
    GuardrailRead,
    ToolInfo,
)
from app.background import named_lock, spawn
from app.db.session import get_databases
from app.domain.bootstrap import (
    ensure_default_agents,
    ensure_default_ai_mode_settings,
    ensure_default_discovery_settings,
)
from app.domain.enums import AssistantProvider
from app.domain.models import (
    AiAgent,
    AiCustomTool,
    AiGuardrail,
    AiMessage,
    AiMessageDelivery,
    AiModeSettings,
    AiRun,
    AiRunStep,
)
from app.llm.agent import (
    DEFAULT_SYSTEM_PROMPT,
    create_run,
    network_scope,
    reap_orphaned_runs,
    running_run_id,
)
from app.llm.agent_tools import _ALLOWED_FLAG, ALL_TOOL_NAMES, TOOL_SCHEMAS
from app.llm.orchestrator import get_context, run_agent
from app.llm.schedule import next_targets

router = APIRouter(prefix="/ai-mode", tags=["ai-mode"])

RUN_START_LOCK = "ai-run-start"

GUARDRAILS = [
    "No shell: every command is an argument list, never a string passed to a shell.",
    "Targets must be a single IP address inside a configured network (loopback is allowed for testing).",
    "nmap flags come from a fixed allowlist: no scripts, no file input or output, no UDP or OS scans.",
    "Output is truncated and every tool call has a hard timeout.",
    "The only write the agent can make is creating an unmanaged service; it cannot delete or monitor.",
    "One run at a time; the loop is bounded by the iteration limit.",
]

async def _read_settings(session: AppSession) -> AiModeSettingsRead:
    settings = await ensure_default_ai_mode_settings(session)
    discovery = await ensure_default_discovery_settings(session)
    read = AiModeSettingsRead.model_validate(settings)
    read.enabled = discovery.ai_mode_enabled
    return read


@router.get("/settings", response_model=AiModeSettingsRead)
async def get_settings(session: AppSession) -> AiModeSettingsRead:
    return await _read_settings(session)


@router.put("/settings", response_model=AiModeSettingsRead)
async def update_settings(
    payload: AiModeSettingsUpdate,
    session: AppSession,
    credentials_session: CredentialsSession,
    credential_service: CredentialServiceDep,
) -> AiModeSettingsRead:
    updates = payload.model_dump(exclude_unset=True)
    current = await ensure_default_ai_mode_settings(session)
    if updates.get("llm_provider", current.llm_provider) == AssistantProvider.OPENROUTER:
        key_id = updates.get("llm_credential_id", current.llm_credential_id)
        await require_credential(credential_service, credentials_session, key_id)
    if "enabled_tools" in updates:
        custom_names = set(await session.scalars(select(AiCustomTool.name)))
        if not set(updates["enabled_tools"]) <= set(ALL_TOOL_NAMES) | custom_names:
            raise HTTPException(status_code=422, detail="enabled_tools contains an unknown tool")
    enabled = updates.pop("enabled", None)

    settings = await ensure_default_ai_mode_settings(session)
    for field, value in updates.items():
        setattr(settings, field, value)
    if enabled is not None:
        (await ensure_default_discovery_settings(session)).ai_mode_enabled = enabled
    await ensure_default_agents(session)
    discoverer = await session.scalar(select(AiAgent).where(AiAgent.name == "discoverer"))
    if discoverer is not None:
        # The single-agent settings page edits the default agent. Only the fields this request actually
        # changed are copied, so toggling AI Mode on or off never overwrites what was set on the Agents page.
        for field in ("system_prompt", "model_override", "max_iterations", "temperature", "enabled_tools"):
            if field in updates:
                setattr(discoverer, field, getattr(settings, field))
    await session.commit()
    return await _read_settings(session)


@router.get("/tools", response_model=AiModeTools)
async def get_tools(session: AppSession) -> AiModeTools:
    settings = await ensure_default_ai_mode_settings(session)
    return AiModeTools(
        default_system_prompt=DEFAULT_SYSTEM_PROMPT,
        tools=[
            ToolInfo(
                name=t["function"]["name"],
                description=t["function"]["description"],
                parameters=t["function"]["parameters"],
                enabled=t["function"]["name"] in settings.enabled_tools,
            )
            for t in TOOL_SCHEMAS
        ],
        guardrails=GUARDRAILS,
        allowed_nmap_flags=_ALLOWED_FLAG.pattern,
    )


async def _summaries(session: AppSession, runs: list[AiRun]) -> list[AiRunSummary]:
    ids = [r.id for r in runs]
    step_rows = await session.execute(
        select(AiRunStep.run_id, func.count()).where(AiRunStep.run_id.in_(ids)).group_by(AiRunStep.run_id)
    )
    steps: dict[int, int] = {run_id: count for run_id, count in step_rows.all()}
    recorded_rows = await session.execute(
        select(AiRunStep.run_id, func.count())
        .where(
            AiRunStep.run_id.in_(ids),
            AiRunStep.kind == "tool",
            AiRunStep.name == "record_service",
            AiRunStep.response["recorded"].as_boolean().is_(True),
        )
        .group_by(AiRunStep.run_id)
    )
    recorded: dict[int, int] = {run_id: count for run_id, count in recorded_rows.all()}
    summaries = []
    for run in runs:
        item = AiRunSummary.model_validate(run)
        context = get_context(run.id)
        item.paused = context is not None and not context.running.is_set()
        item.step_count = steps.get(run.id, 0)
        item.services_recorded = recorded.get(run.id, 0)
        item.entry_agent = str(run.settings_snapshot.get("entry_agent") or "")
        summaries.append(item)
    return summaries


@router.get("/runs", response_model=list[AiRunSummary])
async def list_runs(session: AppSession, limit: int = 50) -> list[AiRunSummary]:
    await reap_orphaned_runs(get_databases())
    result = await session.execute(select(AiRun).order_by(AiRun.id.desc()).limit(limit))
    return await _summaries(session, list(result.scalars().all()))


@router.get("/runs/{run_id}", response_model=AiRunDetail)
async def get_run(run_id: int, session: AppSession) -> AiRunDetail:
    run = await session.get(AiRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    steps = (
        await session.execute(select(AiRunStep).where(AiRunStep.run_id == run_id).order_by(AiRunStep.idx))
    ).scalars().all()
    summary = (await _summaries(session, [run]))[0]
    return AiRunDetail(
        **summary.model_dump(),
        base_url=run.base_url,
        system_prompt=run.system_prompt,
        settings_snapshot=run.settings_snapshot,
        steps=[AiRunStepRead.model_validate(s) for s in steps],
    )


@router.post("/runs", response_model=AiRunSummary, status_code=202)
async def start_run(payload: AiRunStart, session: AppSession) -> AiRunSummary:
    # One run at a time: the check for an active run and the creation of the next must not interleave
    # with another start (a second click, or the scheduler).
    async with named_lock(RUN_START_LOCK):
        return await _start_run_locked(payload, session)


async def _start_run_locked(payload: AiRunStart, session: AppSession) -> AiRunSummary:
    databases = get_databases()
    discovery = await ensure_default_discovery_settings(session)
    if not discovery.ai_mode_enabled:
        raise HTTPException(
            status_code=409,
            detail="AI Mode is disabled; enable it under AI Mode > Model and prompt",
        )
    await reap_orphaned_runs(databases)
    if await running_run_id(databases) is not None:
        raise HTTPException(status_code=409, detail="An AI Mode run is already in progress")

    settings = await ensure_default_ai_mode_settings(session)
    targets = payload.targets
    new_cursor: int | None = None
    if not targets:
        # Same rotating, network-scoped selector a scheduled run uses (next_targets): a manual start
        # with no explicit targets no longer silently sticks to the same devices forever once there
        # are more than max_targets of them, and a device whose network was deleted drops out of
        # rotation along with it instead of being targeted forever.
        targets, new_cursor = await next_targets(databases, settings.schedule_cursor, settings.max_targets)
    if not targets and not await network_scope(session):
        raise HTTPException(
            status_code=400, detail="Nothing to look at: no devices are known and no network is configured"
        )
    targets = targets[: settings.max_targets]

    try:
        run_id = await create_run(databases, targets, payload.dry_run, payload.entry_agent, payload.message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if new_cursor is not None:
        settings.schedule_cursor = new_cursor
        await session.commit()
    spawn(run_agent(databases, run_id), f"ai-run-{run_id}")
    run = await session.get(AiRun, run_id)
    assert run is not None
    await session.refresh(run)
    return (await _summaries(session, [run]))[0]


@router.post("/reset", status_code=204)
async def reset_ai_mode(session: AppSession) -> None:
    """Start from scratch: delete every run, message, agent, custom tool, guardrail and setting, switch
    AI Mode off, and re-create the default settings and agents."""
    async with named_lock(RUN_START_LOCK):
        await reap_orphaned_runs(get_databases())
        if await running_run_id(get_databases()) is not None:
            raise HTTPException(status_code=409, detail="Stop the running AI Mode run before resetting")
        # Children are deleted explicitly: foreign keys are not enforced on pooled connections, so
        # ON DELETE CASCADE cannot be relied on.
        await session.execute(delete(AiMessageDelivery))
        await session.execute(delete(AiMessage))
        await session.execute(delete(AiRunStep))
        await session.execute(delete(AiRun))
        for model in (AiAgent, AiCustomTool, AiGuardrail, AiModeSettings):
            await session.execute(delete(model))
        (await ensure_default_discovery_settings(session)).ai_mode_enabled = False
        await session.commit()
        await ensure_default_agents(session)


# --- User-defined tools and guardrails ---------------------------------------


async def _custom_tool_or_404(session: AppSession, tool_id: int) -> AiCustomTool:
    tool = await session.get(AiCustomTool, tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    return tool


async def _check_tool_name(session: AppSession, name: str, own_id: int | None) -> None:
    if name in ALL_TOOL_NAMES:
        raise HTTPException(status_code=409, detail=f"{name} is a built-in tool name")
    taken = await session.scalar(select(AiCustomTool.id).where(AiCustomTool.name == name))
    if taken is not None and taken != own_id:
        raise HTTPException(status_code=409, detail=f"A tool named {name} already exists")


@router.get("/custom-tools", response_model=list[CustomToolRead])
async def list_custom_tools(session: AppSession) -> list[AiCustomTool]:
    return list((await session.scalars(select(AiCustomTool).order_by(AiCustomTool.name))).all())


@router.post("/custom-tools", response_model=CustomToolRead, status_code=201)
async def create_custom_tool(payload: CustomToolBase, session: AppSession) -> AiCustomTool:
    await _check_tool_name(session, payload.name, None)
    tool = AiCustomTool(**payload.model_dump())
    session.add(tool)
    await session.commit()
    return tool


@router.put("/custom-tools/{tool_id}", response_model=CustomToolRead)
async def update_custom_tool(tool_id: int, payload: CustomToolBase, session: AppSession) -> AiCustomTool:
    tool = await _custom_tool_or_404(session, tool_id)
    await _check_tool_name(session, payload.name, tool_id)
    for field, value in payload.model_dump().items():
        setattr(tool, field, value)
    await session.commit()
    return tool


@router.delete("/custom-tools/{tool_id}", status_code=204)
async def delete_custom_tool(tool_id: int, session: AppSession) -> None:
    tool = await _custom_tool_or_404(session, tool_id)
    settings = await ensure_default_ai_mode_settings(session)
    settings.enabled_tools = [n for n in settings.enabled_tools if n != tool.name]
    await session.delete(tool)
    await session.commit()


@router.get("/guardrails", response_model=list[GuardrailRead])
async def list_guardrails(session: AppSession) -> list[AiGuardrail]:
    return list((await session.scalars(select(AiGuardrail).order_by(AiGuardrail.id))).all())


@router.post("/guardrails", response_model=GuardrailRead, status_code=201)
async def create_guardrail(payload: GuardrailBase, session: AppSession) -> AiGuardrail:
    rule = AiGuardrail(**payload.model_dump())
    session.add(rule)
    await session.commit()
    return rule


@router.put("/guardrails/{rule_id}", response_model=GuardrailRead)
async def update_guardrail(rule_id: int, payload: GuardrailBase, session: AppSession) -> AiGuardrail:
    rule = await session.get(AiGuardrail, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Guardrail not found")
    for field, value in payload.model_dump().items():
        setattr(rule, field, value)
    await session.commit()
    return rule


@router.delete("/guardrails/{rule_id}", status_code=204)
async def delete_guardrail(rule_id: int, session: AppSession) -> None:
    rule = await session.get(AiGuardrail, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Guardrail not found")
    await session.delete(rule)
    await session.commit()
