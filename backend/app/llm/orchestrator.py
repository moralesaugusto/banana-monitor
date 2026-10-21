"""Runs a team of AI Mode agents that coordinate over the message bus.

A run starts by publishing a task message to the entry agent's topic. Each
agent is an asyncio task that waits on its subscription queue; when a message
arrives it runs one bounded tool-calling loop (the same loop the single-agent
version had), then acknowledges the message. Agents talk to each other only by
publishing: through the `publish_message` tool, by their final answer (published
as `result.<name>`), or automatically when they record a service
(`discovery.service.found`). The run is finished when no message is queued,
being handled, or waiting for a human.

Human-in-the-loop: an agent configured with `require_approval` has its outgoing
messages and/or tool calls parked as *held* messages; a human approves (optionally
editing), or rejects with a reason, via the API. A rejection is returned to the
agent as the tool result so it can adapt.
"""

import asyncio
import datetime
import json
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from app.background import spawn
from app.db.session import Databases
from app.domain.enums import EventSeverity
from app.domain.models import AiCustomTool, AiGuardrail, AiMessage, AiRun, Event, utcnow
from app.llm.agent import DEFAULT_SYSTEM_PROMPT, Recorder, _active, _clip
from app.llm.agent_tools import dispatch, schemas_for
from app.llm.agent_tools import save_report as _save_report_tool
from app.llm.bus import APPROVAL_PREFIX, BusError, Envelope, MessageBus, get_message_bus, topic_matches
from app.llm.client import LLMRequestError, call_chat_completions
from app.llm.custom_tools import check_guardrails, run_custom_tool, string_values
from app.llm.custom_tools import schema_for as custom_schema_for
from app.llm.inspect_tools import INSPECT_TOOL_NAMES, MUTATING_TOOLS
from app.llm.provider import load_api_key
from app.llm.tool_base import AgentToolError
from app.llm.usage import record_usage
from app.logging_setup import get_logger
from app.reports.builder import build_snapshot, snapshot_markdown

logger = get_logger(__name__)

LLM_TIMEOUT_SECONDS = 120.0
APPROVAL_TIMEOUT_SECONDS = 600.0
MAX_RUN_SECONDS = 1800.0
TOOL_CONCURRENCY = 4
INCOMPLETE_SUMMARY = "Stopped at the iteration limit."
"""Published instead of a real answer when an agent's loop runs out before it produces one - a sentinel
so the reporter (and anyone else reading result.<agent>) can tell a non-answer from a real one, instead
of treating this short generic string as if it were a real finding about a real host."""


@dataclass
class AgentCfg:
    name: str
    role: str
    system_prompt: str
    base_url: str
    model: str
    temperature: float
    max_iterations: int
    enabled_tools: list[str]
    subscribes: list[str]
    publishes: list[str]
    require_approval: str
    mcp_url_override: str | None = None
    """Replaces every MCP custom tool's mcp_url for this agent's calls only."""
    mcp_timeout_seconds: float = 0.0
    """0 uses custom_tools.MCP_TIMEOUT_SECONDS."""
    allow_changes: bool = False
    llm_timeout_seconds: float = 0.0
    """0 uses the run's default model call timeout."""
    max_run_minutes: float = 0.0
    """0 uses the run's default time limit (AiModeSettings.max_run_minutes). Measured from the run's
    start, same as the run-wide limit - see RunContext.agent_deadlines."""
    credential_id: int | None = None
    """OpenRouter API key reference; the key is read from the credential store for each call."""
    provider: str = "ollama"


@dataclass
class Decision:
    approved: bool
    payload: dict[str, Any] | None = None
    reason: str = ""


@dataclass
class RunContext:
    run_id: int
    databases: Databases
    bus: MessageBus
    recorder: Recorder
    agents: dict[str, AgentCfg]
    base_url: str
    dry_run: bool
    custom_tools: dict[str, AiCustomTool]
    guardrails: list[AiGuardrail]
    running: asyncio.Event = field(default_factory=asyncio.Event)
    """Set while the run is active; cleared while a human has paused it."""
    decisions: dict[int, Decision] = field(default_factory=dict)
    waiters: dict[int, asyncio.Future[Decision]] = field(default_factory=dict)
    summaries: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    recorded: int = 0
    stopped: bool = False
    stop_reason: str | None = None
    """manual | time_limit"""
    task: asyncio.Task[None] | None = None
    started_at: datetime.datetime = field(default_factory=utcnow)
    max_seconds: float = MAX_RUN_SECONDS
    default_max_run_minutes: float = 0.0
    """AiModeSettings.max_run_minutes at run start - the time budget an agent with its own
    max_run_minutes == 0 uses. Falls back to max_seconds/60 when unset (e.g. a RunContext built
    without it, such as in a test)."""
    agent_deadlines: dict[str, datetime.datetime] = field(default_factory=dict)
    """Each agent's own stop point, computed once at run start from its max_run_minutes (or the
    default above when unset) - independent of max_seconds, the run-wide backstop. Populated in
    __post_init__."""
    deadline_task: asyncio.Task[None] | None = None
    """Watches agent_deadlines and stops an agent whose own budget ran out; cancelled alongside the
    per-agent workers when the run ends."""
    llm_timeout_seconds: float = LLM_TIMEOUT_SECONDS
    """How long a single model call may take - configurable (AiModeSettings.llm_call_timeout_seconds)
    since self-hosted Ollama on modest hardware can genuinely need more than the 120s default."""
    agent_state: dict[str, str] = field(default_factory=dict)
    """working (handling a message) | waiting (nothing to do right now)"""
    workers: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    stopped_agents: set[str] = field(default_factory=set)
    """Agents a human stopped during this run; they receive nothing until started again."""
    ollama_gate: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(2))
    """Caps in-flight model calls to an Ollama host across every agent in this run - see
    AiModeSettings.ollama_max_concurrent_calls. Independent of TOOL_CONCURRENCY, which only bounds
    tool-call fan-out within one agent's turn."""
    openrouter_gate: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(4))
    """Same cap for OpenRouter - see AiModeSettings.openrouter_max_concurrent_calls."""

    @property
    def deadline(self) -> datetime.datetime:
        return self.started_at + datetime.timedelta(seconds=self.max_seconds)

    def provider_gate(self, provider: str) -> asyncio.Semaphore:
        return self.openrouter_gate if provider == "openrouter" else self.ollama_gate

    def set_state(self, agent: str, state: str) -> None:
        if self.agent_state.get(agent) != state:
            self.agent_state[agent] = state
            self.bus.emit_run_event(self.run_id, "run")

    def __post_init__(self) -> None:
        self.running.set()
        default_minutes = self.default_max_run_minutes or (self.max_seconds / 60)
        for name, cfg in self.agents.items():
            minutes = cfg.max_run_minutes or default_minutes
            self.agent_deadlines[name] = self.started_at + datetime.timedelta(minutes=minutes)

    def decide(self, message_id: int, decision: Decision) -> None:
        """Called by the API when a human answers a held message."""
        self.decisions[message_id] = decision
        waiter = self.waiters.get(message_id)
        if waiter is not None and not waiter.done():
            waiter.set_result(decision)

    async def wait_for_decision(self, message_id: int) -> Decision:
        if message_id in self.decisions:
            return self.decisions.pop(message_id)
        waiter: asyncio.Future[Decision] = asyncio.get_running_loop().create_future()
        self.waiters[message_id] = waiter
        try:
            return await asyncio.wait_for(waiter, APPROVAL_TIMEOUT_SECONDS)
        except TimeoutError:
            return Decision(False, reason="approval timed out")
        finally:
            self.waiters.pop(message_id, None)
            self.decisions.pop(message_id, None)

    def pause(self) -> None:
        self.running.clear()
        self.bus.emit_run_event(self.run_id, "run")

    def resume(self) -> None:
        self.running.set()
        self.bus.emit_run_event(self.run_id, "run")

    def stop(self, reason: str = "manual") -> None:
        self.stopped = True
        self.stop_reason = reason
        self.running.set()
        if self.task is not None:
            self.task.cancel()


_contexts: dict[int, RunContext] = {}


def _patterns(cfg: AgentCfg) -> list[str]:
    """Every agent can always be given a task directly, which is how a human starts a run at one agent."""
    task_topic = f"task.{cfg.name}"
    return cfg.subscribes if task_topic in cfg.subscribes else [*cfg.subscribes, task_topic]


async def stop_agent(ctx: RunContext, name: str) -> None:
    """Stops one agent mid-run: its current work is cancelled, queued messages are dropped, messages
    it had parked for approval are rejected, and it receives nothing more until started again."""
    worker = ctx.workers.pop(name, None)
    ctx.stopped_agents.add(name)
    await ctx.bus.unsubscribe(ctx.run_id, name)
    if worker is not None:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
    async with ctx.databases.app_session_factory() as session:
        held = list(
            await session.scalars(
                select(AiMessage.id).where(
                    AiMessage.run_id == ctx.run_id, AiMessage.sender == name, AiMessage.status == "held"
                )
            )
        )
    for message_id in held:
        await ctx.bus.reject(message_id, "the agent was stopped")
    ctx.agent_state.pop(name, None)
    ctx.bus.emit_run_event(ctx.run_id, "run")


def start_agent(ctx: RunContext, name: str) -> None:
    """Brings a stopped agent back into the active run."""
    cfg = ctx.agents[name]
    queue = ctx.bus.subscribe(ctx.run_id, name, _patterns(cfg))
    ctx.workers[name] = asyncio.create_task(_agent_loop(ctx, cfg, queue))
    ctx.stopped_agents.discard(name)
    ctx.bus.emit_run_event(ctx.run_id, "run")


AGENT_DEADLINE_SWEEP_SECONDS = 5.0


async def _agent_deadline_sweep(ctx: RunContext) -> None:
    """Stops one agent at a time once its own max_run_minutes (or the AI Mode default, when unset)
    elapses, independently of the run-wide backstop (max_seconds) - the run itself keeps going for
    whichever agents still have budget left. See docs/decisions.md."""
    while True:
        await asyncio.sleep(AGENT_DEADLINE_SWEEP_SECONDS)
        await ctx.running.wait()
        now = utcnow()
        for name, deadline in list(ctx.agent_deadlines.items()):
            if now < deadline or name in ctx.stopped_agents or name not in ctx.workers:
                continue
            cfg = ctx.agents[name]
            minutes = cfg.max_run_minutes or ctx.default_max_run_minutes or (ctx.max_seconds / 60)
            ctx.summaries.setdefault(
                name, f"Stopped automatically: its own {minutes:g} minute time limit was reached."
            )
            await stop_agent(ctx, name)


def spawn_run(databases: Databases, run_id: int) -> None:
    """Runs a created run in the background (used by the scheduler and the API)."""
    spawn(run_agent(databases, run_id), f"ai-run-{run_id}")


def active_context() -> RunContext | None:
    """The run in progress, if any (only one run is active at a time)."""
    return next(iter(_contexts.values()), None)


def get_context(run_id: int) -> RunContext | None:
    return _contexts.get(run_id)


def _team_context(cfg: AgentCfg, agents: dict[str, AgentCfg]) -> str:
    others = [f"- {a.name}: {a.role or 'no description'}" for a in agents.values() if a.name != cfg.name]
    lines = [
        f"\n\nYou are agent '{cfg.name}' in a team that coordinates over a publish/subscribe message bus.",
        f"You receive messages on: {', '.join(cfg.subscribes) or 'nothing'}.",
    ]
    if "publish_message" in cfg.enabled_tools:
        allowed = ", ".join(cfg.publishes) or "none"
        lines.append(f"With publish_message you may send messages to topics matching: {allowed}.")
    lines.append("Your final answer is published automatically for the team." if cfg.publishes else "")
    if others:
        lines.append("Other agents:\n" + "\n".join(others))
    return "\n".join(line for line in lines if line)


async def _publish(
    ctx: RunContext, cfg: AgentCfg, env: Envelope, topic: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """An agent publishes: checks its allow-list, parks the message for a human if it must,
    then delivers it."""
    if not any(topic_matches(p, topic) for p in cfg.publishes):
        raise AgentToolError(f"{cfg.name} may not publish to {topic!r}; allowed: {cfg.publishes}")
    hold = cfg.require_approval in ("messages", "both")
    try:
        message = await ctx.bus.publish(
            ctx.run_id,
            topic,
            cfg.name,
            payload,
            correlation_id=env.correlation_id,
            hops=env.hops + 1,
            hold=hold,
        )
    except BusError as exc:
        raise AgentToolError(str(exc)) from exc
    if hold:
        ctx.set_state(cfg.name, "held")
        try:
            decision = await ctx.wait_for_decision(message.id)
        finally:
            ctx.set_state(cfg.name, "tool")
        if not decision.approved:
            await ctx.bus.reject(message.id, decision.reason or "rejected")
            raise AgentToolError(f"a human rejected this message: {decision.reason or 'no reason given'}")
        await ctx.bus.release(message.id, decision.payload)
    return {"published": True, "topic": topic, "message_id": message.id}


async def _ask_human_about_tool(
    ctx: RunContext, cfg: AgentCfg, env: Envelope, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Parks a tool call as an approval request; returns the (possibly edited) arguments."""
    request = await ctx.bus.publish(
        ctx.run_id,
        f"{APPROVAL_PREFIX}tool.{cfg.name}",
        cfg.name,
        {"tool": name, "arguments": arguments},
        correlation_id=env.correlation_id,
        hops=env.hops,
        hold=True,
    )
    ctx.set_state(cfg.name, "held")
    try:
        decision = await ctx.wait_for_decision(request.id)
    finally:
        ctx.set_state(cfg.name, "tool")
    if not decision.approved:
        await ctx.bus.reject(request.id, decision.reason or "rejected")
        raise AgentToolError(f"a human rejected this tool call: {decision.reason or 'no reason given'}")
    await ctx.bus.release(request.id, decision.payload)
    edited = (decision.payload or {}).get("arguments")
    return edited if isinstance(edited, dict) else arguments


async def _run_tool(
    ctx: RunContext, cfg: AgentCfg, env: Envelope, name: str, raw_args: Any
) -> tuple[Any, dict[str, Any]]:
    started = time.monotonic()
    arguments: Any = raw_args
    try:
        arguments = raw_args if isinstance(raw_args, dict) else json.loads(raw_args or "{}")
        if name not in cfg.enabled_tools:
            raise AgentToolError(f"unknown or disabled tool {name!r}")
        if name in MUTATING_TOOLS and not cfg.allow_changes:
            raise AgentToolError(f"{cfg.name} may not change hosts, so {name!r} is refused")
        asks_human = cfg.require_approval in ("tools", "both") or name in MUTATING_TOOLS
        if asks_human and name != "publish_message":
            arguments = await _ask_human_about_tool(ctx, cfg, env, name, arguments)
        if name in INSPECT_TOOL_NAMES:
            check_guardrails(ctx.guardrails, string_values(arguments))
        if name == "publish_message":
            result: Any = await _publish(
                ctx, cfg, env, str(arguments.get("topic", "")), {"text": str(arguments.get("content", ""))}
            )
        elif name in ctx.custom_tools:
            result = await run_custom_tool(
                ctx.databases,
                ctx.custom_tools[name],
                ctx.guardrails,
                arguments,
                cfg.mcp_url_override,
                cfg.mcp_timeout_seconds,
            )
        else:
            result = await dispatch(
                ctx.databases, name, arguments, enabled=cfg.enabled_tools, dry_run=ctx.dry_run
            )
        if name == "record_service" and (result.get("recorded") or result.get("dry_run")):
            ctx.recorded += 1 if result.get("recorded") else 0
            await _announce_service(ctx, cfg, env, arguments, result)
        if name == "report_open_ports" and (result.get("reported") or result.get("dry_run")):
            await _announce_ports(ctx, cfg, env, arguments, result)
    except (AgentToolError, json.JSONDecodeError) as exc:
        if not isinstance(arguments, dict):
            arguments = {"raw": raw_args}
        result = {"error": str(exc)}
    await ctx.recorder.step(
        kind="tool",
        name=name,
        agent=cfg.name,
        request=_clip(arguments),
        response=_clip(result),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return result, arguments


async def _announce_service(
    ctx: RunContext, cfg: AgentCfg, env: Envelope, arguments: dict[str, Any], result: dict[str, Any]
) -> None:
    """Recording a service is an event other agents may care about, so it is
    announced on the bus automatically rather than relying on the model to do so."""
    payload = {k: arguments.get(k) for k in ("ip", "port", "service_type", "name", "product", "version")}
    payload["service_id"] = result.get("service_id")
    if result.get("dry_run"):
        payload["dry_run"] = True  # announced so the team still reacts, but nothing was written
    try:
        await ctx.bus.publish(
            ctx.run_id,
            "discovery.service.found",
            cfg.name,
            payload,
            correlation_id=env.correlation_id,
            hops=env.hops + 1,
        )
    except BusError as exc:
        logger.warning("service_announcement_dropped", error=str(exc))


async def _announce_ports(
    ctx: RunContext, cfg: AgentCfg, env: Envelope, arguments: dict[str, Any], result: dict[str, Any]
) -> None:
    """Finding open ports on a host is handed off automatically, same as _announce_service, so the
    agent that identifies what is running on them (reviewer, by default) does not depend on the
    model remembering to publish_message itself."""
    payload = {"ip": arguments.get("ip"), "ports": arguments.get("ports")}
    if result.get("dry_run"):
        payload["dry_run"] = True
    try:
        await ctx.bus.publish(
            ctx.run_id,
            "discovery.ports.found",
            cfg.name,
            payload,
            correlation_id=env.correlation_id,
            hops=env.hops + 1,
        )
    except BusError as exc:
        logger.warning("ports_announcement_dropped", error=str(exc))


def _message_text(env: Envelope) -> str:
    payload = env.payload
    if set(payload) == {"text"}:
        return f"Message on topic {env.topic} from {env.sender}:\n{payload['text']}"
    text = payload.get("text", "")
    targets = payload.get("targets")
    networks = payload.get("networks")
    extra = {k: v for k, v in payload.items() if k not in ("text", "targets", "networks")}
    lines = [f"Message on topic {env.topic} from {env.sender}:", str(text)]
    if targets:
        # Spelled out plainly and separately from the task text: a target list is authoritative and
        # must not be second-guessed against wording in the text above, which may be more general
        # ("every host") than the actual, narrower list this run was started with.
        lines.append(
            f"\nTargets (the only hosts this is about, regardless of wording above): {', '.join(targets)}"
        )
    if networks:
        lines.append("\nConfigured networks (the complete list):")
        lines.extend(
            f"- {n['name']}: {n['cidr']} ({n['devices']} known devices"
            f"{'; none yet, sweep it with discover_hosts if you have that tool' if not n['devices'] else ''})"
            for n in networks
        )
    if extra:
        lines.append(f"\n{json.dumps(extra)}")
    return "\n".join(lines)


async def _handle(ctx: RunContext, cfg: AgentCfg, env: Envelope) -> None:
    """One bounded tool-calling loop in response to one message."""
    tools = {t["function"]["name"]: t for t in schemas_for(cfg.enabled_tools)}
    tools.update({n: custom_schema_for(t) for n, t in ctx.custom_tools.items() if n in cfg.enabled_tools})
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (cfg.system_prompt or DEFAULT_SYSTEM_PROMPT) + _team_context(cfg, ctx.agents),
        },
        {"role": "user", "content": _message_text(env)},
    ]
    summary = INCOMPLETE_SUMMARY
    gate = asyncio.Semaphore(TOOL_CONCURRENCY)
    for _ in range(cfg.max_iterations):
        await ctx.running.wait()
        started = time.monotonic()
        api_key = await load_api_key(ctx.databases, cfg.credential_id)
        ctx.set_state(cfg.name, "llm")
        async with ctx.provider_gate(cfg.provider):
            response = await call_chat_completions(
                base_url=cfg.base_url,
                api_key=api_key,
                model=cfg.model,
                messages=messages,
                tools=list(tools.values()),
                timeout=cfg.llm_timeout_seconds or ctx.llm_timeout_seconds,
                temperature=cfg.temperature,
            )
        message = response["choices"][0]["message"]
        usage = response.get("usage") or {}
        requested = message.get("tool_calls") or []
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        await ctx.recorder.step(
            kind="llm",
            name=cfg.model,
            agent=cfg.name,
            request=_clip(messages),
            response=_clip(
                {
                    "content": message.get("content"),
                    "reasoning": message.get("reasoning") or message.get("thinking"),
                    "tool_calls": [
                        {"name": c["function"]["name"], "arguments": c["function"]["arguments"]}
                        for c in requested
                    ],
                }
            ),
            duration_ms=int((time.monotonic() - started) * 1000),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        await ctx.recorder.add_tokens(prompt_tokens, completion_tokens)
        await record_usage(
            ctx.databases,
            source="agent",
            agent=cfg.name,
            provider=cfg.provider,
            model=cfg.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

        if not requested:
            summary = message.get("content") or ""
            break
        messages.append(message)
        ctx.set_state(cfg.name, "tool")
        # A model often asks for a scan per host in one reply. Run them together (a few at a time):
        # one after another, ten 60 s timeouts turn a single model turn into ten minutes.
        async def run_one(call: dict[str, Any]) -> Any:
            async with gate:
                function = call["function"]
                result, _ = await _run_tool(ctx, cfg, env, function["name"], function["arguments"])
            return result

        results = await asyncio.gather(*(run_one(call) for call in requested))
        for call, result in zip(requested, results, strict=True):
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id", call["function"]["name"]),
                    "content": json.dumps(result, default=str),
                }
            )

    ctx.summaries.setdefault(cfg.name, summary)
    topic = f"result.{cfg.name}"
    if summary and any(topic_matches(p, topic) for p in cfg.publishes):
        result_payload: dict[str, Any] = {"text": summary}
        if summary == INCOMPLETE_SUMMARY:
            # Nothing real to report - give whoever reads this the actual targets from the original
            # message instead of leaving them to guess hosts from a generic sentence (see REPORTER_PROMPT).
            result_payload["incomplete"] = True
            original_targets = env.payload.get("targets") if isinstance(env.payload, dict) else None
            if original_targets:
                result_payload["targets"] = original_targets
        try:
            await _publish(ctx, cfg, env, topic, result_payload)
        except AgentToolError as exc:
            await _record_error(ctx, cfg.name, str(exc))


async def _record_error(ctx: RunContext, agent: str, error: str) -> None:
    """Writes an error step to the trace; failing to do so must never take the agent down with it."""
    try:
        await ctx.recorder.step(kind="error", agent=agent, request={}, response={"error": error})
    except Exception:  # noqa: BLE001
        logger.warning("ai_error_step_not_recorded", agent=agent, exc_info=True)


async def _publish_failure(ctx: RunContext, cfg: AgentCfg, env: Envelope, error: str) -> None:
    """A failed agent still answers on its result topic, marked incomplete, so the agents waiting for it
    (and the trace) know it is not coming instead of never starting."""
    topic = f"result.{cfg.name}"
    if not any(topic_matches(p, topic) for p in cfg.publishes):
        return
    text = f"{cfg.name} failed before it could answer: {error}"
    payload: dict[str, Any] = {"text": text, "incomplete": True}
    targets = env.payload.get("targets") if isinstance(env.payload, dict) else None
    if targets:
        payload["targets"] = targets
    try:
        await _publish(ctx, cfg, env, topic, payload)
    except AgentToolError as exc:
        await _record_error(ctx, cfg.name, str(exc))


async def _reporter_fallback_report(ctx: RunContext, error: str) -> None:
    """If reporter itself fails (e.g. its own LLM call times out) before producing anything, a plain
    snapshot-based report is still better than nothing: the same renderer the manual "Save report"
    button already uses, so a run that gets this far still leaves something behind instead of just an
    error with nothing salvaged."""
    try:
        snapshot = await build_snapshot(ctx.databases)
        content = (
            f"**Automatic fallback.** The reporter agent's own analysis failed ({error}) before it could "
            "finish, so this is the current network snapshot rather than a narrative written from "
            "whatever triggered this run.\n\n" + snapshot_markdown(snapshot)
        )
        title = "Reporter fallback (analysis failed)"
        await _save_report_tool(ctx.databases, {"title": title, "content": content})
    except Exception:  # noqa: BLE001 - a failed fallback must not raise past an already-failed agent
        logger.warning("ai_reporter_fallback_failed", exc_info=True)


async def _agent_loop(ctx: RunContext, cfg: AgentCfg, queue: "asyncio.Queue[Envelope]") -> None:
    ctx.set_state(cfg.name, "waiting")
    while True:
        env = await queue.get()
        try:
            await ctx.running.wait()
            ctx.set_state(cfg.name, "working")
            await _handle(ctx, cfg, env)
        except Exception as exc:  # noqa: BLE001 - one bad message must not kill this agent for the rest of the run
            error = f"{cfg.name}: {str(exc) or type(exc).__name__}"
            ctx.errors.append(error)
            logger.warning("ai_agent_failed", agent=cfg.name, error=error)
            await _record_error(ctx, cfg.name, error)
            await _publish_failure(ctx, cfg, env, error)
            if cfg.name == "reporter":
                await _reporter_fallback_report(ctx, error)
        finally:
            await ctx.bus.ack(env, cfg.name)
            ctx.set_state(cfg.name, "waiting")


def _join_summaries(summaries: dict[str, str]) -> str | None:
    if len(summaries) == 1:
        return next(iter(summaries.values()))
    return "\n\n".join(f"{name}: {text}" for name, text in summaries.items()) or None


async def run_agent(databases: Databases, run_id: int) -> None:
    """Runs every agent snapshotted into the run until the team goes idle."""
    bus = get_message_bus()
    _active.add(run_id)
    error: str | None = None
    ctx: RunContext | None = None
    try:
        async with databases.app_session_factory() as session:
            run = await session.get(AiRun, run_id)
            assert run is not None
            targets, dry_run, base_url = list(run.targets), run.dry_run, run.base_url
            snapshot = dict(run.settings_snapshot)
            custom_tools = {
                t.name: t for t in await session.scalars(select(AiCustomTool).where(AiCustomTool.enabled))
            }
            guardrails = list(await session.scalars(select(AiGuardrail).where(AiGuardrail.enabled)))

        agents = {
            a["name"]: AgentCfg(
                name=a["name"],
                role=a["role"],
                system_prompt=a["system_prompt"],
                base_url=a.get("base_url") or base_url,
                model=a["model"],
                temperature=a["temperature"],
                max_iterations=a["max_iterations"],
                enabled_tools=a["enabled_tools"],
                mcp_url_override=a.get("mcp_url_override"),
                mcp_timeout_seconds=float(a.get("mcp_timeout_seconds") or 0),
                subscribes=a["subscribes"],
                publishes=a["publishes"],
                require_approval=a["require_approval"],
                allow_changes=a.get("allow_changes", False),
                llm_timeout_seconds=float(a.get("llm_timeout_seconds") or 0),
                max_run_minutes=float(a.get("max_run_minutes") or 0),
                credential_id=a.get("credential_id"),
                provider=a.get("provider", "ollama"),
            )
            for a in snapshot["agents"]
        }
        ctx = RunContext(
            run_id=run_id,
            databases=databases,
            bus=bus,
            recorder=Recorder(databases, run_id),
            agents=agents,
            base_url=base_url,
            dry_run=dry_run,
            custom_tools=custom_tools,
            guardrails=guardrails,
            task=asyncio.current_task(),
            max_seconds=float(snapshot.get("max_run_seconds") or MAX_RUN_SECONDS),
            default_max_run_minutes=float(snapshot.get("default_max_run_minutes") or 0),
            llm_timeout_seconds=float(snapshot.get("llm_timeout_seconds") or LLM_TIMEOUT_SECONDS),
            ollama_gate=asyncio.Semaphore(max(1, int(snapshot.get("ollama_max_concurrent_calls") or 2))),
            openrouter_gate=asyncio.Semaphore(
                max(1, int(snapshot.get("openrouter_max_concurrent_calls") or 4))
            ),
        )
        _contexts[run_id] = ctx
        bus.open_run(run_id)
        bus.emit_run_event(run_id, "run")
        ctx.deadline_task = asyncio.create_task(_agent_deadline_sweep(ctx))
        # Subscribe every agent before the first message is published, so none can be missed.
        for name in agents:
            start_agent(ctx, name)

        entry = snapshot["entry_agent"]
        text = snapshot.get("message") or (
            f"Discover and record services on: {', '.join(targets)}"
            if targets
            else "No devices are known yet, so find them yourself: sweep every configured network with "
            "discover_hosts, then probe what it finds and record every service you identify."
        )
        await bus.publish(
            run_id,
            f"task.{entry}",
            "human",
            {"text": text, "targets": targets, "networks": snapshot.get("networks", [])},
            reply_to=f"result.{entry}",
        )
        try:
            await asyncio.wait_for(bus.wait_idle(run_id), ctx.max_seconds)
        except TimeoutError:
            ctx.stop_reason = "time_limit"  # the budget ran out: stop automatically, keep what was found
        if ctx.errors and error is None:
            error = "; ".join(ctx.errors[:3])
    except LLMRequestError as exc:
        error = str(exc) or type(exc).__name__
        logger.warning("ai_mode_run_failed", error=error)
    except asyncio.CancelledError:
        if ctx is None or not ctx.stopped:
            error = "cancelled"
            raise
    finally:
        running_workers = list(ctx.workers.values()) if ctx else []
        if ctx is not None and ctx.deadline_task is not None:
            running_workers.append(ctx.deadline_task)
        for worker in running_workers:
            worker.cancel()
        await asyncio.gather(*running_workers, return_exceptions=True)
        _contexts.pop(run_id, None)
        bus.close_run(run_id)
        _active.discard(run_id)
        summary = _join_summaries(ctx.summaries if ctx else {})
        if ctx is not None and ctx.stop_reason:
            notice = (
                "Stopped by a human."
                if ctx.stop_reason == "manual"
                else f"Stopped automatically: the {ctx.max_seconds / 60:g} minute time limit was reached."
            )
            summary = f"{notice}\n\n{summary}" if summary else notice
        recorded = ctx.recorded if ctx else 0
        async with databases.app_session_factory() as session:
            run_row = await session.get(AiRun, run_id)
            if run_row is not None:
                run_row.status = "error" if error else "done"
                run_row.error = error
                run_row.summary = summary
                run_row.stop_reason = ctx.stop_reason if ctx else None
                run_row.finished_at = utcnow()
            session.add(
                Event(
                    source="ai_mode",
                    severity=EventSeverity.ERROR if error else EventSeverity.INFO,
                    category="discovery",
                    message=(
                        f"AI Mode run #{run_id}: {'error' if error else 'done'}"
                        f"{f', stopped ({ctx.stop_reason})' if ctx and ctx.stop_reason else ''}"
                        f" ({recorded} services recorded)"
                    ),
                )
            )
            await session.commit()
        bus.emit_run_event(run_id, "run")
