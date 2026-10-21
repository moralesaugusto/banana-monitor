"""Agents, the message log, human-in-the-loop decisions and run controls for multi-agent AI Mode."""

import json
import re
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import AppSession, CredentialServiceDep, CredentialsSession, require_credential
from app.api.routes.ai_mode import start_run
from app.api.schemas.ai_mode import (
    AgentBase,
    AgentRead,
    AgentStartRequest,
    AgentState,
    AiRunStart,
    AiRunSummary,
    AiStatus,
    BusAgentHealth,
    BusGauge,
    BusHealth,
    BusHeldMessage,
    BusOverview,
    BusParty,
    BusProblem,
    BusRoute,
    BusTopicStats,
    Decision,
    HumanMessage,
    MessageRead,
    RunStatus,
    ScheduleRead,
    ScheduleUpdate,
    VerifyResult,
    WorkflowUpdate,
)
from app.domain.bootstrap import (
    ensure_default_agents,
    ensure_default_ai_mode_settings,
    ensure_default_discovery_settings,
)
from app.domain.enums import AssistantProvider
from app.domain.models import (
    AiAgent,
    AiCustomTool,
    AiMessage,
    AiMessageDelivery,
    AiModeSettings,
    AiRun,
    utcnow,
)
from app.llm.agent_verify import changing_tools_without_permission, unknown_tools, verify_agent
from app.llm.bus import (
    APPROVAL_PREFIX,
    MAX_HOPS,
    MAX_MESSAGES_PER_RUN,
    BusError,
    get_message_bus,
    topic_matches,
    valid_pattern,
)
from app.llm.client import LLMRequestError, list_models
from app.llm.orchestrator import (
    APPROVAL_TIMEOUT_SECONDS,
    MAX_RUN_SECONDS,
    active_context,
    get_context,
    start_agent,
    stop_agent,
)
from app.llm.orchestrator import Decision as HumanDecision
from app.llm.provider import effective_endpoint
from app.llm.schedule import loop_anchor, next_run_at

router = APIRouter(prefix="/ai-mode", tags=["ai-agents"])

_NO_START_TARGET = AgentStartRequest()
"""A shared, empty default body for /agents/{id}/start - an omitted request body means no explicit target."""


async def _validate_agent(
    session: AppSession,
    payload: AgentBase,
    own_id: int | None,
    credentials_session: CredentialsSession,
    credential_service: CredentialServiceDep,
) -> None:
    defaults = await ensure_default_ai_mode_settings(session)
    endpoint = effective_endpoint(
        defaults,
        provider=payload.provider,
        base_url=payload.base_url,
        model=payload.model_override,
        credential_id=payload.credential_id,
    )
    if endpoint.provider == AssistantProvider.OPENROUTER:
        await require_credential(credential_service, credentials_session, endpoint.credential_id)
    if not endpoint.model:
        raise HTTPException(
            status_code=422, detail="Set a model: the default model belongs to the other provider"
        )
    custom = set(await session.scalars(select(AiCustomTool.name)))
    if unknown := unknown_tools(payload.enabled_tools, custom):
        raise HTTPException(status_code=422, detail=f"unknown tools: {unknown}")
    if changing := changing_tools_without_permission(payload.enabled_tools, payload.allow_changes):
        raise HTTPException(
            status_code=422,
            detail=f"{changing} change hosts: tick 'May change hosts' on this agent first",
        )
    taken = await session.scalar(select(AiAgent.id).where(AiAgent.name == payload.name))
    if taken is not None and taken != own_id:
        raise HTTPException(status_code=409, detail=f"An agent named {payload.name} already exists")


async def _agent_or_404(session: AppSession, agent_id: int) -> AiAgent:
    agent = await session.get(AiAgent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.get("/agents", response_model=list[AgentRead])
async def list_agents(session: AppSession) -> list[AiAgent]:
    await ensure_default_agents(session)
    return list((await session.scalars(select(AiAgent).order_by(AiAgent.id))).all())


@router.post("/agents/verify", response_model=VerifyResult)
async def verify_agent_settings(
    payload: AgentBase, session: AppSession, agent_id: int | None = None
) -> VerifyResult:
    """Pre-flight checks for a draft or saved agent (tools, host and model, readers, prerequisites)."""
    return await verify_agent(session, payload, agent_id)


@router.post("/agents", response_model=AgentRead, status_code=201)
async def create_agent(
    payload: AgentBase,
    session: AppSession,
    credentials_session: CredentialsSession,
    credential_service: CredentialServiceDep,
) -> AiAgent:
    await _validate_agent(session, payload, None, credentials_session, credential_service)
    agent = AiAgent(**payload.model_dump())
    session.add(agent)
    await session.commit()
    return agent


@router.put("/agents/{agent_id}", response_model=AgentRead)
async def update_agent(
    agent_id: int,
    payload: AgentBase,
    session: AppSession,
    credentials_session: CredentialsSession,
    credential_service: CredentialServiceDep,
) -> AiAgent:
    agent = await _agent_or_404(session, agent_id)
    await _validate_agent(session, payload, agent_id, credentials_session, credential_service)
    for field, value in payload.model_dump(exclude={"workflow_x", "workflow_y"}).items():
        setattr(agent, field, value)
    await session.commit()
    return agent


@router.patch("/agents/{agent_id}/workflow", response_model=AgentRead)
async def update_agent_workflow(agent_id: int, payload: WorkflowUpdate, session: AppSession) -> AiAgent:
    """Canvas edits: move a node and switch an agent on or off without resending its whole config."""
    agent = await _agent_or_404(session, agent_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)
    await session.commit()
    return agent


@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(agent_id: int, session: AppSession) -> None:
    await session.delete(await _agent_or_404(session, agent_id))
    await session.commit()


@router.get("/ollama-models")
async def list_ollama_models(session: AppSession, base_url: str = "") -> dict[str, object]:
    """Models served by an Ollama host (OpenAI-compatible `/models`), so the Agents form can offer a choice.
    Empty `base_url` means the agents' default host."""
    host = base_url or (await ensure_default_ai_mode_settings(session)).llm_base_url
    if not re.match(r"^https?://\S+$", host):
        raise HTTPException(status_code=422, detail="base_url must be an http(s) URL")
    try:
        models = await list_models(host)
    except LLMRequestError as exc:
        raise HTTPException(status_code=502, detail=f"Could not list models from {host}: {exc}") from exc
    return {"base_url": host, "models": models}


@router.post("/agents/{agent_id}/stop", status_code=202)
async def stop_one_agent(agent_id: int, session: AppSession) -> dict[str, str]:
    """Stops this agent in the active run; the others carry on."""
    agent = await _agent_or_404(session, agent_id)
    context = active_context()
    if context is None or agent.name not in context.agents or agent.name in context.stopped_agents:
        raise HTTPException(status_code=409, detail=f"{agent.name} is not running")
    await stop_agent(context, agent.name)
    return {"status": "stopped"}


@router.post("/agents/{agent_id}/start", status_code=202)
async def start_one_agent(
    agent_id: int, session: AppSession, payload: AgentStartRequest = _NO_START_TARGET
) -> dict[str, int | str]:
    """Idle: starts a run with this agent first. During a run: brings it back if it was stopped by hand.
    An explicit target/message runs this agent against hosts regardless of whether it has discovered
    them on its own yet."""
    agent = await _agent_or_404(session, agent_id)
    if not agent.enabled:
        raise HTTPException(status_code=409, detail=f"{agent.name} is disabled; enable it first")
    context = active_context()
    if context is not None:
        if agent.name not in context.stopped_agents:
            raise HTTPException(status_code=409, detail=f"{agent.name} is already running")
        start_agent(context, agent.name)
        if payload.targets or payload.message:
            text = payload.message or f"Investigate: {', '.join(payload.targets)}"
            await context.bus.publish(
                context.run_id,
                f"task.{agent.name}",
                "human",
                {"text": text, "targets": payload.targets},
                reply_to=f"result.{agent.name}",
            )
        return {"status": "started", "run_id": context.run_id}
    run = await start_run(
        AiRunStart(entry_agent=agent.name, targets=payload.targets, message=payload.message), session
    )
    return {"status": "started", "run_id": run.id}


# --- Schedule and status ------------------------------------------------------------


async def _schedule_read(session: AppSession, settings: AiModeSettings) -> ScheduleRead:
    read = ScheduleRead.model_validate(settings)
    if await session.scalar(select(AiRun.id).where(AiRun.status == "running").limit(1)) is None:
        read.next_run_at = next_run_at(
            read.schedule_enabled,
            await loop_anchor(session, read.last_scheduled_at),
            read.schedule_interval_seconds,
        )
    return read


@router.get("/schedule", response_model=ScheduleRead)
async def get_schedule(session: AppSession) -> ScheduleRead:
    return await _schedule_read(session, await ensure_default_ai_mode_settings(session))


@router.put("/schedule", response_model=ScheduleRead)
async def update_schedule(payload: ScheduleUpdate, session: AppSession) -> ScheduleRead:
    updates = payload.model_dump(exclude_unset=True)
    entry = updates.get("schedule_entry_agent")
    if entry is not None and await session.scalar(select(AiAgent.id).where(AiAgent.name == entry)) is None:
        raise HTTPException(status_code=422, detail=f"No agent named {entry}")
    settings = await ensure_default_ai_mode_settings(session)
    for field, value in updates.items():
        setattr(settings, field, value)
    await session.commit()
    return await _schedule_read(session, settings)


@router.get("/status", response_model=AiStatus)
async def get_status(session: AppSession) -> AiStatus:
    """What every agent is doing right now: working, waiting, paused, scheduled, stopped or disabled."""
    await ensure_default_agents(session)
    settings = await ensure_default_ai_mode_settings(session)
    ai_enabled = (await ensure_default_discovery_settings(session)).ai_mode_enabled
    agents = list((await session.scalars(select(AiAgent).order_by(AiAgent.id))).all())
    schedule = await _schedule_read(session, settings)
    last = await session.scalar(select(AiRun).order_by(AiRun.id.desc()).limit(1))

    run_id = await session.scalar(select(AiRun.id).where(AiRun.status == "running").limit(1))
    context = get_context(run_id) if run_id is not None else None
    run: RunStatus | None = None
    queued: dict[str, int] = {}
    if context is not None:
        run_row = await session.get(AiRun, context.run_id)
        run = RunStatus(
            id=context.run_id,
            started_by=run_row.started_by if run_row else "manual",
            started_at=context.started_at,
            deadline_at=context.deadline,
            paused=not context.running.is_set(),
        )
        queued = get_message_bus().queued(context.run_id)

    scheduled = schedule.schedule_enabled and ai_enabled
    states: list[AgentState] = []
    for agent in agents:
        state: Literal["working", "waiting", "paused", "scheduled", "stopped", "disabled"]
        activity: Literal["llm", "tool", "held"] | None = None
        if not agent.enabled:
            state = "disabled"
        elif context is not None and agent.name in context.stopped_agents:
            state = "stopped"  # stopped by hand during this run
        elif context is not None and agent.name in context.agents:
            if run is not None and run.paused:
                state = "paused"
            else:
                raw = context.agent_state.get(agent.name)
                if raw in ("llm", "tool", "held"):
                    state = "working"
                    activity = raw  # type: ignore[assignment]
                else:
                    state = "working" if raw == "working" else "waiting"
        elif scheduled:
            state = "scheduled"  # every enabled agent takes part in the next scheduled run
        else:
            state = "stopped"
        states.append(
            AgentState(
                name=agent.name,
                display_name=agent.display_name,
                enabled=agent.enabled,
                state=state,
                activity=activity,
                queued=queued.get(agent.name, 0),
            )
        )
    return AiStatus(
        ai_enabled=ai_enabled,
        run=run,
        last_run=AiRunSummary.model_validate(last) if last is not None else None,
        agents=states,
        schedule=schedule,
    )


# --- Bus visibility ----------------------------------------------------------------


@router.get("/bus/route", response_model=BusRoute)
async def bus_route(topic: str, session: AppSession) -> BusRoute:
    """Who would receive a message on `topic`, and who is allowed to publish to it, with the pattern that
    decided each - computed by the same matcher the bus uses."""
    topic = topic.strip()
    if not topic or not valid_pattern(topic) or "*" in topic or "#" in topic:
        return BusRoute(topic=topic, valid=False, subscribers=[], publishers=[])
    agents = list((await session.scalars(select(AiAgent).order_by(AiAgent.id))).all())

    def parties(patterns_of: Literal["subscribes", "publishes"]) -> list[BusParty]:
        found = []
        for agent in agents:
            pattern = next((p for p in getattr(agent, patterns_of) if topic_matches(p, topic)), None)
            if pattern is not None:
                found.append(BusParty(agent=agent.name, enabled=agent.enabled, pattern=pattern))
        return found

    return BusRoute(
        topic=topic, valid=True, subscribers=parties("subscribes"), publishers=parties("publishes")
    )


@router.get("/bus/overview", response_model=BusOverview)
async def bus_overview(session: AppSession, run_id: int | None = None) -> BusOverview:
    """Per-topic traffic: message counts, who published, who received and the delivery outcomes. One run, or
    every run when `run_id` is omitted. `approval.*` topics are human prompts, never routed, so left out."""
    routed = ~AiMessage.topic.like("approval.%")
    scope = [routed] + ([AiMessage.run_id == run_id] if run_id is not None else [])

    stats = (
        await session.execute(
            select(
                AiMessage.topic,
                func.count(),
                func.sum(func.iif(AiMessage.status == "held", 1, 0)),
                func.max(AiMessage.ts),
            )
            .where(*scope)
            .group_by(AiMessage.topic)
        )
    ).all()
    senders: dict[str, set[str]] = {}
    for topic, sender in (
        await session.execute(select(AiMessage.topic, AiMessage.sender).where(*scope).distinct())
    ).all():
        senders.setdefault(topic, set()).add(sender)
    recipients: dict[str, set[str]] = {}
    outcomes: dict[str, dict[str, int]] = {}
    for topic, recipient, state, count in (
        await session.execute(
            select(AiMessage.topic, AiMessageDelivery.recipient, AiMessageDelivery.state, func.count())
            .join(AiMessageDelivery, AiMessageDelivery.message_id == AiMessage.id)
            .where(*scope)
            .group_by(AiMessage.topic, AiMessageDelivery.recipient, AiMessageDelivery.state)
        )
    ).all():
        recipients.setdefault(topic, set()).add(recipient)
        by_state = outcomes.setdefault(topic, {})
        by_state[state] = by_state.get(state, 0) + count

    topics = [
        BusTopicStats(
            topic=topic,
            messages=count,
            held=int(held or 0),
            last_ts=last_ts,
            publishers=sorted(senders.get(topic, ())),
            recipients=sorted(recipients.get(topic, ())),
            deliveries=outcomes.get(topic, {}),
        )
        for topic, count, held, last_ts in stats
    ]
    topics.sort(key=lambda t: t.last_ts, reverse=True)
    return BusOverview(run_id=run_id, total_messages=sum(t.messages for t in topics), topics=topics)


@router.get("/bus/health", response_model=BusHealth)
async def bus_health(run_id: int, session: AppSession) -> BusHealth:
    """How close a run is to its limits, what each agent has queued or waiting on a human, and what went
    wrong: messages a human rejected and deliveries discarded because their agent was stopped."""
    run = await session.get(AiRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    now = utcnow()
    routed = [AiMessage.run_id == run_id, ~AiMessage.topic.like(f"{APPROVAL_PREFIX}%")]

    used, max_hops = (
        await session.execute(select(func.count(), func.max(AiMessage.hops)).where(*routed))
    ).one()
    held_rows = (
        await session.execute(
            select(AiMessage)
            .where(AiMessage.run_id == run_id, AiMessage.status == "held")
            .order_by(AiMessage.id)
        )
    ).scalars().all()
    held = [
        BusHeldMessage(
            message_id=m.id,
            topic=m.topic,
            sender=m.sender,
            ts=m.ts,
            age_seconds=(now - m.ts).total_seconds(),
            overdue=(now - m.ts).total_seconds() > APPROVAL_TIMEOUT_SECONDS,
        )
        for m in held_rows
    ]
    rejected = (
        await session.execute(
            select(AiMessage)
            .where(AiMessage.run_id == run_id, AiMessage.status == "rejected")
            .order_by(AiMessage.id)
        )
    ).scalars().all()
    dropped = (
        await session.execute(
            select(AiMessage, AiMessageDelivery.recipient)
            .join(AiMessageDelivery, AiMessageDelivery.message_id == AiMessage.id)
            .where(AiMessage.run_id == run_id, AiMessageDelivery.state == "dropped")
            .order_by(AiMessage.id)
        )
    ).all()
    problems = [
        BusProblem(
            kind="rejected", message_id=m.id, topic=m.topic, sender=m.sender, recipient=None,
            reason=m.note or "Rejected by a human", ts=m.ts,
        )
        for m in rejected
    ] + [
        BusProblem(
            kind="dropped", message_id=m.id, topic=m.topic, sender=m.sender, recipient=recipient,
            reason=f"{recipient} was stopped before it handled this message", ts=m.ts,
        )
        for m, recipient in dropped
    ]
    problems.sort(key=lambda p: p.message_id)

    context = get_context(run_id)
    queued = get_message_bus().queued(run_id) if context is not None else {}
    names = [a.name for a in (await session.scalars(select(AiAgent).order_by(AiAgent.id))).all()]
    agents = [
        BusAgentHealth(
            name=name,
            queued=queued.get(name, 0),
            working=context is not None
            and context.agent_state.get(name) in ("working", "llm", "tool", "held"),
            held=sum(1 for m in held if m.sender == name),
            dropped=sum(1 for p in problems if p.kind == "dropped" and p.recipient == name),
        )
        for name in names
    ]
    end = run.finished_at or now
    return BusHealth(
        run_id=run_id,
        active=context is not None,
        messages=BusGauge(used=used, limit=MAX_MESSAGES_PER_RUN),
        hops=BusGauge(used=max_hops or 0, limit=MAX_HOPS),
        seconds=BusGauge(
            used=(end - run.started_at).total_seconds(),
            limit=float(run.settings_snapshot.get("max_run_seconds") or MAX_RUN_SECONDS),
        ),
        approval_timeout_seconds=APPROVAL_TIMEOUT_SECONDS,
        agents=agents,
        held=held,
        problems=problems,
    )


# --- Message log -----------------------------------------------------------------


@router.get("/messages", response_model=list[MessageRead])
async def list_messages(
    session: AppSession,
    run_id: int | None = None,
    topic: str | None = None,
    sender: str | None = None,
    limit: int = 500,
) -> list[AiMessage]:
    query = (
        select(AiMessage)
        .options(selectinload(AiMessage.deliveries))
        .order_by(AiMessage.id.desc())
        .limit(limit)
    )
    if run_id is not None:
        query = query.where(AiMessage.run_id == run_id)
    if topic:
        query = query.where(AiMessage.topic.like(f"{topic}%"))
    if sender:
        query = query.where(AiMessage.sender == sender)
    return list(reversed((await session.scalars(query)).all()))


@router.post("/messages", response_model=MessageRead, status_code=201)
async def publish_as_human(payload: HumanMessage, session: AppSession) -> AiMessage:
    """A human publishes to the bus of a running run, exactly like an agent would."""
    bus = get_message_bus()
    if not bus.is_open(payload.run_id):
        raise HTTPException(status_code=409, detail="That run is not active")
    try:
        envelope = await bus.publish(
            payload.run_id,
            payload.topic,
            "human",
            {"text": payload.text},
            correlation_id=payload.correlation_id,
        )
    except BusError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    message = await session.scalar(
        select(AiMessage).where(AiMessage.id == envelope.id).options(selectinload(AiMessage.deliveries))
    )
    assert message is not None
    return message


async def _decide(message_id: int, session: AppSession, decision: HumanDecision) -> None:
    message = await session.get(AiMessage, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    context = get_context(message.run_id)
    if message.status != "held" or context is None:
        raise HTTPException(status_code=409, detail="Nothing is waiting for a decision on this message")
    context.decide(message_id, decision)


@router.post("/messages/{message_id}/approve", status_code=202)
async def approve_message(message_id: int, payload: Decision, session: AppSession) -> dict[str, str]:
    await _decide(message_id, session, HumanDecision(True, payload.payload))
    return {"status": "approved"}


@router.post("/messages/{message_id}/reject", status_code=202)
async def reject_message(message_id: int, payload: Decision, session: AppSession) -> dict[str, str]:
    await _decide(message_id, session, HumanDecision(False, reason=payload.reason))
    return {"status": "rejected"}


# --- Run controls ------------------------------------------------------------------


def _context_or_409(run_id: int):  # type: ignore[no-untyped-def]
    context = get_context(run_id)
    if context is None:
        raise HTTPException(status_code=409, detail="That run is not active")
    return context


@router.post("/runs/{run_id}/pause", status_code=202)
async def pause_run(run_id: int) -> dict[str, str]:
    _context_or_409(run_id).pause()
    return {"status": "paused"}


@router.post("/runs/{run_id}/resume", status_code=202)
async def resume_run(run_id: int) -> dict[str, str]:
    _context_or_409(run_id).resume()
    return {"status": "running"}


@router.post("/runs/{run_id}/stop", status_code=202)
async def stop_run(run_id: int) -> dict[str, str]:
    _context_or_409(run_id).stop()
    return {"status": "stopping"}


# --- Live feed ----------------------------------------------------------------------


@router.get("/events")
async def events() -> StreamingResponse:
    """Server-sent events: one small JSON event per bus message, delivery or run change.
    The UI refetches the log when one arrives, so the log stays the source of truth."""

    async def stream() -> AsyncIterator[str]:
        yield ": connected\n\n"
        async for event in get_message_bus().events():
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
