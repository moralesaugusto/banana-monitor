import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.session import get_databases
from app.domain.models import AiMessage, AiMessageDelivery, AiRun, Base
from app.llm.bus import MAX_HOPS, BusError, MessageBus, get_message_bus, topic_matches, valid_pattern


@pytest.mark.parametrize(
    ("pattern", "topic", "expected"),
    [
        ("task.discoverer", "task.discoverer", True),
        ("task.discoverer", "task.reviewer", False),
        ("task.*", "task.reviewer", True),
        ("task.*", "task.reviewer.extra", False),
        ("task.*", "task", False),
        ("result.#", "result.reviewer", True),
        ("result.#", "result.a.b.c", True),
        ("result.#", "result", True),
        ("#", "anything.at.all", True),
        ("discovery.*.found", "discovery.service.found", True),
        ("discovery.*.found", "discovery.service.lost", False),
    ],
)
def test_topic_matches(pattern: str, topic: str, expected: bool) -> None:
    assert topic_matches(pattern, topic) is expected


def test_valid_pattern() -> None:
    assert valid_pattern("result.#") and valid_pattern("a.*.b") and valid_pattern("task.discoverer")
    assert not valid_pattern("a.#.b") and not valid_pattern("Bad Topic") and not valid_pattern("a..b")


@pytest_asyncio.fixture
async def bus() -> MessageBus:
    databases = get_databases()
    async with databases.app_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with databases.app_session_factory() as session:
        session.add(AiRun())
        await session.commit()
    instance = get_message_bus()
    instance.open_run(1)
    return instance


async def test_publish_fans_out_to_matching_subscribers_and_logs_first(bus: MessageBus) -> None:
    reviewer = bus.subscribe(1, "reviewer", ["discovery.#"])
    other = bus.subscribe(1, "other", ["task.*"])
    sender_queue = bus.subscribe(1, "discoverer", ["discovery.#"])

    envelope = await bus.publish(1, "discovery.service.found", "discoverer", {"port": 22})

    assert envelope.recipients == ["reviewer"]  # not the sender, not a non-matching pattern
    assert reviewer.get_nowait().payload == {"port": 22}
    assert other.empty() and sender_queue.empty()
    async with get_databases().app_session_factory() as session:
        rows = (await session.scalars(select(AiMessageDelivery))).all()
    assert [(r.recipient, r.state) for r in rows] == [("reviewer", "delivered")]


async def test_ack_marks_delivery_and_makes_the_run_idle(bus: MessageBus) -> None:
    queue = bus.subscribe(1, "reviewer", ["result.#"])
    envelope = await bus.publish(1, "result.x", "human", {})
    assert not bus._state(1).idle.is_set()

    received = queue.get_nowait()
    await bus.ack(received, "reviewer")

    await asyncio.wait_for(bus.wait_idle(1), 1)
    async with get_databases().app_session_factory() as session:
        delivery = await session.scalar(
            select(AiMessageDelivery).where(AiMessageDelivery.message_id == envelope.id)
        )
    assert delivery is not None and delivery.state == "acked"


async def test_held_message_is_not_delivered_until_released(bus: MessageBus) -> None:
    queue = bus.subscribe(1, "reviewer", ["task.*"])
    held = await bus.publish(1, "task.reviewer", "discoverer", {"text": "old"}, hold=True)
    assert queue.empty() and held.status == "held"
    assert not bus._state(1).idle.is_set()  # a pending approval keeps the run alive

    await bus.release(held.id, {"text": "edited"})

    assert queue.get_nowait().payload == {"text": "edited"}
    async with get_databases().app_session_factory() as session:
        message = await session.get(AiMessage, held.id)
    assert message is not None and message.status == "delivered"


async def test_rejected_message_is_never_delivered(bus: MessageBus) -> None:
    queue = bus.subscribe(1, "reviewer", ["task.*"])
    held = await bus.publish(1, "task.reviewer", "discoverer", {}, hold=True)

    await bus.reject(held.id, "not now")

    assert queue.empty()
    await asyncio.wait_for(bus.wait_idle(1), 1)
    with pytest.raises(BusError):
        await bus.release(held.id)  # already decided


async def test_approval_topics_are_never_routed(bus: MessageBus) -> None:
    queue = bus.subscribe(1, "spy", ["#"])
    await bus.publish(1, "approval.tool.discoverer", "discoverer", {"tool": "run_nmap"}, hold=True)
    assert queue.empty()


async def test_loop_protection(bus: MessageBus) -> None:
    with pytest.raises(BusError, match="hop limit"):
        await bus.publish(1, "task.x", "a", {}, hops=MAX_HOPS + 1)
    with pytest.raises(BusError, match="invalid topic"):
        await bus.publish(1, "Bad Topic", "a", {})
    with pytest.raises(BusError, match="invalid topic"):
        await bus.publish(1, "task.*", "a", {})


async def test_event_feed_reports_messages(bus: MessageBus) -> None:
    feed = bus.events()
    pending = asyncio.ensure_future(feed.__anext__())
    await asyncio.sleep(0)  # let the listener register
    await bus.publish(1, "task.x", "human", {})
    event = await asyncio.wait_for(pending, 1)
    assert event["type"] == "message" and event["run_id"] == 1
    await feed.aclose()
