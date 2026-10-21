"""In-process publish/subscribe message bus for AI Mode agents.

Agents never call each other. An agent publishes a message to a *topic*; the
bus hands a copy to every agent whose *subscription pattern* matches that
topic. This is the standard pub/sub model (the same one MQTT or NATS use),
kept in-process because this app is a single process.

Concepts, each visible in the UI and the `ai_messages` table:

- Topic: dot-separated name such as `task.discoverer` or `discovery.service.found`.
- Pattern: `*` matches exactly one segment, `#` matches the rest (`result.#`).
- Envelope: id, topic, sender, payload, correlation id (one conversation),
  reply_to, hops (how many agent-to-agent steps deep the message is).
- Delivery: one row per recipient, `delivered` once it is in the recipient's
  queue and `acked` once the recipient finished handling it.
- Held: a message waiting for a human to approve, edit or reject it; nobody
  receives it until then.

The database log is written before delivery, so it is the source of truth.
In-memory queues are lost on restart; the log is not.
"""

import asyncio
import datetime
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from sqlalchemy import select

from app.db.session import Databases, get_databases
from app.domain.models import AiMessage, AiMessageDelivery

MAX_MESSAGES_PER_RUN = 500
"""A runaway guard, not a budget: every recorded service is announced and every announcement can be
answered, so a real sweep of a few /24s needs well over a hundred. Loops are stopped by MAX_HOPS."""
MAX_HOPS = 8
APPROVAL_PREFIX = "approval."
"""Topic prefix for human-approval requests (e.g. a tool call). Never routed to subscribers."""

_SEGMENT = re.compile(r"^[a-z0-9_-]+$")


class BusError(RuntimeError):
    pass


def valid_pattern(pattern: str) -> bool:
    segments = pattern.split(".")
    for i, segment in enumerate(segments):
        if segment == "#":
            if i != len(segments) - 1:
                return False
        elif segment != "*" and not _SEGMENT.match(segment):
            return False
    return True


def topic_matches(pattern: str, topic: str) -> bool:
    """`*` = exactly one segment, `#` = zero or more trailing segments."""
    p_parts, t_parts = pattern.split("."), topic.split(".")
    for i, part in enumerate(p_parts):
        if part == "#":
            return True
        if i >= len(t_parts) or (part != "*" and part != t_parts[i]):
            return False
    return len(p_parts) == len(t_parts)


@dataclass
class Envelope:
    id: int
    run_id: int
    topic: str
    sender: str
    payload: dict[str, Any]
    correlation_id: str
    reply_to: str | None
    hops: int
    status: str
    recipients: list[str] = field(default_factory=list)


@dataclass
class _RunState:
    subs: list[tuple[str, list[str], asyncio.Queue[Envelope]]] = field(default_factory=list)
    count: int = 0
    inflight: int = 0
    idle: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self) -> None:
        self.idle.set()

    def add(self, n: int = 1) -> None:
        self.inflight += n
        self.idle.clear()

    def done(self) -> None:
        self.inflight = max(0, self.inflight - 1)
        if self.inflight == 0:
            self.idle.set()


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class MessageBus:
    def __init__(self, databases: Databases) -> None:
        self._databases = databases
        self._runs: dict[int, _RunState] = {}
        self._listeners: set[asyncio.Queue[dict[str, Any]]] = set()

    # --- lifecycle -------------------------------------------------------------

    def open_run(self, run_id: int) -> None:
        self._runs[run_id] = _RunState()

    def close_run(self, run_id: int) -> None:
        self._runs.pop(run_id, None)

    def is_open(self, run_id: int) -> bool:
        return run_id in self._runs

    def subscribe(self, run_id: int, agent: str, patterns: list[str]) -> asyncio.Queue[Envelope]:
        queue: asyncio.Queue[Envelope] = asyncio.Queue()
        self._state(run_id).subs.append((agent, patterns, queue))
        return queue

    async def unsubscribe(self, run_id: int, agent: str) -> int:
        """Stops delivering to `agent`: its subscriptions are removed and messages still waiting in its
        queue are dropped (their delivery state becomes `dropped`) so the run can still go idle."""
        state = self._runs.get(run_id)
        if state is None:
            return 0
        dropped: list[Envelope] = []
        for sub in [s for s in state.subs if s[0] == agent]:
            state.subs.remove(sub)
            while not sub[2].empty():
                dropped.append(sub[2].get_nowait())
        if dropped:
            async with self._databases.app_session_factory() as session:
                for envelope in dropped:
                    delivery = await session.scalar(
                        select(AiMessageDelivery).where(
                            AiMessageDelivery.message_id == envelope.id, AiMessageDelivery.recipient == agent
                        )
                    )
                    if delivery is not None:
                        delivery.state = "dropped"
                        delivery.updated_at = _now()
                await session.commit()
            for _ in dropped:
                state.done()
        self._emit({"type": "run", "run_id": run_id})
        return len(dropped)

    def _state(self, run_id: int) -> _RunState:
        state = self._runs.get(run_id)
        if state is None:
            raise BusError(f"run {run_id} is not active")
        return state

    # --- publish ---------------------------------------------------------------

    def _recipients(self, state: _RunState, topic: str, sender: str) -> list[str]:
        if topic.startswith(APPROVAL_PREFIX):
            return []
        names = []
        for agent, patterns, _ in state.subs:
            if agent != sender and agent not in names and any(topic_matches(p, topic) for p in patterns):
                names.append(agent)
        return names

    async def publish(
        self,
        run_id: int,
        topic: str,
        sender: str,
        payload: dict[str, Any],
        *,
        correlation_id: str | None = None,
        reply_to: str | None = None,
        hops: int = 0,
        hold: bool = False,
    ) -> Envelope:
        """Logs the message, then (unless held for a human) delivers it."""
        state = self._state(run_id)
        if not valid_pattern(topic) or "*" in topic or "#" in topic:
            raise BusError(f"invalid topic {topic!r}: use dot-separated lowercase words")
        approval = topic.startswith(APPROVAL_PREFIX)
        if not approval:
            if hops > MAX_HOPS:
                raise BusError(f"hop limit ({MAX_HOPS}) reached; the conversation is looping")
            if state.count >= MAX_MESSAGES_PER_RUN:
                raise BusError(f"message limit ({MAX_MESSAGES_PER_RUN}) for this run reached")
            state.count += 1

        recipients = self._recipients(state, topic, sender)
        async with self._databases.app_session_factory() as session:
            message = AiMessage(
                run_id=run_id,
                topic=topic,
                sender=sender,
                payload=payload,
                correlation_id=correlation_id or uuid.uuid4().hex[:12],
                reply_to=reply_to,
                hops=hops,
                status="held" if hold else "delivered",
            )
            message.deliveries = [
                AiMessageDelivery(recipient=r, state="pending" if hold else "delivered") for r in recipients
            ]
            session.add(message)
            await session.commit()
            envelope = self._envelope(message, recipients)

        if hold:
            state.add()
        else:
            self._fanout(state, envelope)
        self._emit({"type": "message", "run_id": run_id, "message_id": envelope.id})
        return envelope

    def _envelope(self, message: AiMessage, recipients: list[str]) -> Envelope:
        return Envelope(
            id=message.id,
            run_id=message.run_id,
            topic=message.topic,
            sender=message.sender,
            payload=dict(message.payload or {}),
            correlation_id=message.correlation_id,
            reply_to=message.reply_to,
            hops=message.hops,
            status=message.status,
            recipients=recipients,
        )

    def _fanout(self, state: _RunState, envelope: Envelope) -> None:
        for agent, _, queue in state.subs:
            if agent in envelope.recipients:
                state.add()
                queue.put_nowait(envelope)

    # --- human gate ------------------------------------------------------------

    async def release(self, message_id: int, payload: dict[str, Any] | None = None) -> Envelope:
        """A human approved a held message (optionally with an edited payload)."""
        async with self._databases.app_session_factory() as session:
            message = await self._held(session, message_id)
            if payload is not None:
                message.payload = payload
            approval = message.topic.startswith(APPROVAL_PREFIX)
            message.status = "approved" if approval else "delivered"
            for delivery in message.deliveries:
                delivery.state = "delivered"
                delivery.updated_at = _now()
            await session.commit()
            envelope = self._envelope(message, [d.recipient for d in message.deliveries])
        state = self._state(envelope.run_id)
        self._fanout(state, envelope)
        state.done()  # the hold itself is over
        self._emit({"type": "message", "run_id": envelope.run_id, "message_id": message_id})
        return envelope

    async def reject(self, message_id: int, reason: str) -> Envelope:
        async with self._databases.app_session_factory() as session:
            message = await self._held(session, message_id)
            message.status = "rejected"
            message.note = reason
            for delivery in message.deliveries:
                delivery.state = "rejected"
                delivery.updated_at = _now()
            await session.commit()
            envelope = self._envelope(message, [])
        self._state(envelope.run_id).done()
        self._emit({"type": "message", "run_id": envelope.run_id, "message_id": message_id})
        return envelope

    async def _held(self, session: Any, message_id: int) -> AiMessage:
        message = await session.scalar(select(AiMessage).where(AiMessage.id == message_id))
        if message is None:
            raise BusError("message not found")
        if message.status != "held":
            raise BusError("message is not waiting for approval")
        await session.refresh(message, ["deliveries"])
        return message  # type: ignore[no-any-return]

    # --- consume ---------------------------------------------------------------

    async def ack(self, envelope: Envelope, agent: str) -> None:
        """The recipient finished handling a message."""
        async with self._databases.app_session_factory() as session:
            delivery = await session.scalar(
                select(AiMessageDelivery).where(
                    AiMessageDelivery.message_id == envelope.id, AiMessageDelivery.recipient == agent
                )
            )
            if delivery is not None:
                delivery.state = "acked"
                delivery.updated_at = _now()
                await session.commit()
        state = self._runs.get(envelope.run_id)
        if state is not None:
            state.done()
        self._emit({"type": "delivery", "run_id": envelope.run_id, "message_id": envelope.id})

    def queued(self, run_id: int) -> dict[str, int]:
        """Messages waiting in each subscriber's queue (not yet picked up)."""
        state = self._runs.get(run_id)
        return {} if state is None else {agent: queue.qsize() for agent, _, queue in state.subs}

    async def wait_idle(self, run_id: int) -> None:
        await self._state(run_id).idle.wait()

    # --- live feed -------------------------------------------------------------

    def _emit(self, event: dict[str, Any]) -> None:
        for listener in self._listeners:
            listener.put_nowait(event)

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Live feed of bus activity (used by the SSE endpoint)."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._listeners.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._listeners.discard(queue)

    def emit_run_event(self, run_id: int, kind: str) -> None:
        self._emit({"type": kind, "run_id": run_id})


@lru_cache
def get_message_bus() -> MessageBus:
    return MessageBus(get_databases())
