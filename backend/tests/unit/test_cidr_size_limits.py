"""A range's size must be judged from its prefix, never by enumerating its hosts: an IPv6 /64 has 2**64."""

import ipaddress

import pytest

from app.db.session import get_databases
from app.discovery import network_map, network_scanner
from app.domain.models import Base as AppBase
from app.domain.models import Network
from app.llm import agent_tools


@pytest.fixture
async def databases():
    dbs = get_databases()
    async with dbs.app_engine.begin() as conn:
        await conn.run_sync(AppBase.metadata.create_all)
    async with dbs.app_session_factory() as session:
        from app.domain.bootstrap import ensure_default_site

        site = await ensure_default_site(session)
        session.add(Network(site_id=site.id, name="v6", cidr="fd00::/48"))
        session.add(Network(site_id=site.id, name="big", cidr="10.0.0.0/8"))
        await session.commit()
    yield dbs
    await dbs.dispose()


@pytest.fixture
def no_enumeration(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(self: object) -> None:
        raise AssertionError("enumerated hosts of a range before checking its size")

    monkeypatch.setattr(ipaddress.IPv4Network, "hosts", refuse)
    monkeypatch.setattr(ipaddress.IPv6Network, "hosts", refuse)


@pytest.mark.parametrize(
    "cidr",
    [
        "10.0.0.0/24",
        "10.0.0.0/30",
        "10.0.0.0/31",
        "10.0.0.1/32",
        "fd00::/120",
        "fd00::/126",
        "fd00::/127",
        "fd00::1/128",
    ],
)
def test_host_count_matches_what_hosts_would_yield(cidr: str) -> None:
    net = ipaddress.ip_network(cidr, strict=False)
    assert network_scanner.host_count(net) == len(list(net.hosts()))


@pytest.mark.usefixtures("no_enumeration")
async def test_scan_cidr_rejects_an_oversized_range_without_enumerating_it(databases) -> None:
    with pytest.raises(ValueError, match="more than the 10 limit"):
        await network_scanner.scan_cidr(databases, "fd00::/64", max_hosts=10)


@pytest.mark.usefixtures("no_enumeration")
@pytest.mark.parametrize("cidr", ["fd00::/64", "10.0.0.0/8"])
async def test_ai_discovery_rejects_an_oversized_range_inside_a_network_without_enumerating_it(
    databases, cidr: str
) -> None:
    with pytest.raises(agent_tools.AgentToolError, match="scan limit"):
        await agent_tools.discover_hosts(databases, {"cidr": cidr})


@pytest.mark.usefixtures("no_enumeration")
async def test_network_map_reports_an_oversized_network_as_truncated_without_enumerating_it(
    databases,
) -> None:
    async with databases.app_session_factory() as session:
        from sqlalchemy import select

        network = (await session.scalars(select(Network).where(Network.name == "v6"))).one()
    result = await network_map.build_network_map(databases, network)
    assert result["truncated"] is True
