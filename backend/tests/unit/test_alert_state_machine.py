import datetime

import pytest

from app.alerting.state_machine import AlertStateSnapshot, evaluate_transition
from app.domain.enums import AlertState

NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
LONG_AGO = NOW - datetime.timedelta(seconds=1000)
RECENTLY = NOW - datetime.timedelta(seconds=1)


@pytest.mark.parametrize(
    ("state", "changed_at", "breach", "expected_state", "expected_changed", "expected_notify"),
    [
        (AlertState.OK, RECENTLY, False, AlertState.OK, False, False),
        (AlertState.OK, RECENTLY, True, AlertState.PENDING, True, False),
        (AlertState.PENDING, RECENTLY, False, AlertState.OK, True, False),
        (AlertState.PENDING, RECENTLY, True, AlertState.PENDING, False, False),
        (AlertState.PENDING, LONG_AGO, True, AlertState.FIRING, True, True),
        (AlertState.FIRING, RECENTLY, True, AlertState.FIRING, False, False),
        (AlertState.FIRING, RECENTLY, False, AlertState.RESOLVED, True, True),
        (AlertState.RESOLVED, RECENTLY, True, AlertState.FIRING, True, True),
        (AlertState.RESOLVED, RECENTLY, False, AlertState.RESOLVED, False, False),
        (AlertState.RESOLVED, LONG_AGO, False, AlertState.OK, True, False),
        (AlertState.FLAPPING, RECENTLY, True, AlertState.FLAPPING, False, False),
        (AlertState.FLAPPING, LONG_AGO, False, AlertState.OK, True, False),
    ],
)
def test_transitions(state, changed_at, breach, expected_state, expected_changed, expected_notify) -> None:
    snapshot = AlertStateSnapshot(state=state, state_changed_at=changed_at)

    transition = evaluate_transition(snapshot, breach, NOW, for_duration=60.0, recovery_duration=60.0)

    assert transition.new_state == expected_state
    assert transition.state_changed == expected_changed
    assert transition.should_notify == expected_notify
