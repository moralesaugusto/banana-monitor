import pytest

from app.domain.enums import DeviceType
from app.domain.roles import infer_role


@pytest.mark.parametrize(
    ("services", "expected"),
    [
        ([(8006, "")], "Hypervisor"),
        ([(53, ""), (3000, "")], "DNS / ad-blocker"),
        ([(22, ""), (443, "")], "Linux server"),
        ([(445, "")], "Windows / file server"),
        ([(80, "")], "Web appliance"),
        ([], "Unclassified"),
    ],
)
def test_infer_role_for_other_devices(services: list[tuple[int | None, str]], expected: str) -> None:
    assert infer_role(DeviceType.OTHER, services) == expected


def test_explicit_type_wins() -> None:
    assert infer_role(DeviceType.NETWORK_EQUIPMENT, [(8006, "")]) == "Network equipment"
