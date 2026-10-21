import datetime
from dataclasses import dataclass

from app.domain.enums import AlertState

DEFAULT_FOR_DURATION_SECONDS = 60.0
DEFAULT_RECOVERY_DURATION_SECONDS = 30.0
DEFAULT_FLAP_WINDOW_SECONDS = 600.0
DEFAULT_FLAP_THRESHOLD = 3


@dataclass
class AlertStateSnapshot:
    state: AlertState
    state_changed_at: datetime.datetime


@dataclass
class Transition:
    new_state: AlertState
    state_changed: bool
    should_notify: bool
    message: str | None


def evaluate_transition(
    snapshot: AlertStateSnapshot,
    breach: bool,
    now: datetime.datetime,
    for_duration: float = DEFAULT_FOR_DURATION_SECONDS,
    recovery_duration: float = DEFAULT_RECOVERY_DURATION_SECONDS,
) -> Transition:
    """Pure ok -> pending -> firing -> resolved -> ok transition logic.

    Flap detection/dampening is layered on top by the engine (which owns the
    persisted flap_score) - this function only ever proposes FIRING, never
    FLAPPING, on a resolved->breach transition.
    """
    elapsed = (now - snapshot.state_changed_at).total_seconds()
    state = snapshot.state

    if state == AlertState.OK:
        if breach:
            return Transition(AlertState.PENDING, True, False, "breach detected, entering pending")
        return Transition(AlertState.OK, False, False, None)

    if state == AlertState.PENDING:
        if not breach:
            return Transition(AlertState.OK, True, False, "breach cleared before firing")
        if elapsed >= for_duration:
            return Transition(AlertState.FIRING, True, True, "breach persisted, now firing")
        return Transition(AlertState.PENDING, False, False, None)

    if state == AlertState.FIRING:
        if not breach:
            return Transition(AlertState.RESOLVED, True, True, "breach cleared, resolving")
        return Transition(AlertState.FIRING, False, False, None)

    if state == AlertState.RESOLVED:
        if breach:
            return Transition(AlertState.FIRING, True, True, "re-fired during recovery window")
        if elapsed >= recovery_duration:
            return Transition(AlertState.OK, True, False, "recovery confirmed")
        return Transition(AlertState.RESOLVED, False, False, None)

    if state == AlertState.FLAPPING:
        if not breach and elapsed >= recovery_duration:
            return Transition(AlertState.OK, True, False, "flapping quieted down")
        return Transition(AlertState.FLAPPING, False, False, None)

    return Transition(state, False, False, None)
