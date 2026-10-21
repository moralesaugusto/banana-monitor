"""compute_delta: what changed between two build_snapshot() results - the server-side diff the
reporter agent's get_status_delta tool is built on, so deltas never depend on a model eyeballing
two raw snapshots."""

from app.reports.builder import compute_delta


def _device(name: str, ip: str, status: str, services: list[dict] | None = None) -> dict:
    return {"name": name, "ip": ip, "status": status, "services": services or []}


def _service(name: str, port: int, status: str) -> dict:
    return {"name": name, "port": port, "status": status}


def _alert(rule: str, entity: str, state: str) -> dict:
    return {"rule": rule, "entity": entity, "state": state}


def _snapshot(devices: list[dict], alerts: list[dict] | None = None, generated_at: str = "t1") -> dict:
    return {"generated_at": generated_at, "devices": devices, "active_alerts": alerts or []}


def test_devices_added_and_removed() -> None:
    previous = _snapshot([_device("web1", "10.0.0.5", "up")])
    current = _snapshot([_device("web2", "10.0.0.6", "up")])

    delta = compute_delta(previous, current)
    assert delta["devices_added"] == ["web2"]
    assert delta["devices_removed"] == ["web1"]
    assert delta["since"] == "t1"


def test_device_status_change_is_detected() -> None:
    previous = _snapshot([_device("web1", "10.0.0.5", "up")])
    current = _snapshot([_device("web1", "10.0.0.5", "down")])

    delta = compute_delta(previous, current)
    assert delta["device_status_changes"] == [{"name": "web1", "ip": "10.0.0.5", "from": "up", "to": "down"}]
    assert delta["devices_added"] == [] and delta["devices_removed"] == []


def test_service_status_change_is_detected_within_an_unchanged_device() -> None:
    previous = _snapshot([_device("web1", "10.0.0.5", "up", [_service("http", 80, "up")])])
    current = _snapshot([_device("web1", "10.0.0.5", "up", [_service("http", 80, "down")])])

    delta = compute_delta(previous, current)
    assert delta["device_status_changes"] == []
    assert delta["service_status_changes"] == [
        {"device": "web1", "service": "http", "port": 80, "from": "up", "to": "down"}
    ]


def test_alerts_new_and_resolved() -> None:
    previous = _snapshot([], [_alert("device-down", "device web1", "firing")])
    current = _snapshot([], [_alert("service-down", "service http", "firing")])

    delta = compute_delta(previous, current)
    assert delta["new_alerts"] == [{"rule": "service-down", "entity": "service http", "state": "firing"}]
    assert delta["resolved_alerts"] == [{"rule": "device-down", "entity": "device web1", "state": "firing"}]


def test_no_change_means_empty_delta() -> None:
    snapshot = _snapshot([_device("web1", "10.0.0.5", "up", [_service("http", 80, "up")])])
    delta = compute_delta(snapshot, snapshot)
    assert delta == {
        "since": "t1",
        "devices_added": [],
        "devices_removed": [],
        "device_status_changes": [],
        "service_status_changes": [],
        "new_alerts": [],
        "resolved_alerts": [],
    }


def test_a_device_with_no_ip_falls_back_to_its_name_as_the_key() -> None:
    previous = _snapshot([{"name": "unassigned-1", "ip": None, "status": "up", "services": []}])
    current = _snapshot([{"name": "unassigned-1", "ip": None, "status": "down", "services": []}])

    delta = compute_delta(previous, current)
    assert delta["device_status_changes"] == [
        {"name": "unassigned-1", "ip": None, "from": "up", "to": "down"}
    ]
