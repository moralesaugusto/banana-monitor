from unittest.mock import AsyncMock, patch

import pytest

from app.discovery import reachability
from app.domain.enums import HealthStatus


@pytest.mark.parametrize(
    ("ping", "open_ports", "expected"),
    [
        (True, [], HealthStatus.UP),
        (False, [22], HealthStatus.DEGRADED),
        (False, [], HealthStatus.DOWN),
    ],
)
async def test_probe_device(ping: bool, open_ports: list[int], expected: HealthStatus) -> None:
    with (
        patch.object(reachability, "ping_host", AsyncMock(return_value=ping)),
        patch.object(reachability, "scan_ports", AsyncMock(return_value=open_ports)),
    ):
        assert await reachability.probe_device("10.0.0.5", [22]) is expected
