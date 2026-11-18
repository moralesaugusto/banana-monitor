import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import (
    AiAgent,
    AiCustomTool,
    AiModeSettings,
    AssistantConfig,
    DiscoverySettings,
    Site,
    TelegramConfig,
)
from app.prompts import load_prompt

DEFAULT_SITE_NAME = "Default"
HEXSTRIKE_TOOLS_FILE = Path(__file__).parent / "hexstrike_tools.json"
HEXSTRIKE_MCP_URL = "http://10.0.0.10:8891/mcp"
"""Changing HexStrike VMs afterward is a one-field edit (tajonaso's "MCP server override" on its edit
page, AiAgent.mcp_url_override), not a reseed - this constant only matters for a brand-new install."""

TAJONASO_PROMPT = load_prompt("tajonaso")


async def ensure_default_site(session: AsyncSession) -> Site:
    result = await session.execute(select(Site).order_by(Site.id).limit(1))
    site = result.scalar_one_or_none()
    if site is not None:
        return site

    site = Site(name=DEFAULT_SITE_NAME, description="Created automatically on first run")
    session.add(site)
    await session.commit()
    await session.refresh(site)
    return site


async def ensure_default_assistant_config(session: AsyncSession) -> AssistantConfig:
    result = await session.execute(select(AssistantConfig).order_by(AssistantConfig.id).limit(1))
    config = result.scalar_one_or_none()
    if config is not None:
        return config

    config = AssistantConfig()  # column defaults come from BANANA_OLLAMA_BASE_URL / BANANA_OLLAMA_MODEL
    session.add(config)
    await session.commit()
    await session.refresh(config)
    return config


async def ensure_default_discovery_settings(session: AsyncSession) -> DiscoverySettings:
    result = await session.execute(select(DiscoverySettings).order_by(DiscoverySettings.id).limit(1))
    settings = result.scalar_one_or_none()
    if settings is not None:
        return settings

    settings = DiscoverySettings()
    session.add(settings)
    await session.commit()
    await session.refresh(settings)
    return settings


async def ensure_default_ai_mode_settings(session: AsyncSession) -> AiModeSettings:
    result = await session.execute(select(AiModeSettings).order_by(AiModeSettings.id).limit(1))
    settings = result.scalar_one_or_none()
    if settings is not None:
        return settings

    settings = AiModeSettings()
    session.add(settings)
    await session.commit()
    await session.refresh(settings)
    return settings


LEGACY_REVIEWER_PROMPT = (
    "You are a reviewer agent in a home-LAN monitoring platform. You receive a message each time "
    "another agent records a service. Check it is plausible: if the port is open, use run_nc once "
    "to read its banner and compare with the claimed service type. If the claimed service type is "
    "https or another TLS port and a plain run_nc call returns nothing, that is expected - retry once "
    "with tls set rather than repeating the same plain call. Reply with one short sentence: confirmed, "
    "or what looks wrong."
)
LEGACY_REVIEWER_PROMPT_PRE_NMAP = (
    "You are a reviewer agent in a home-LAN monitoring platform. You receive a message each time "
    "another agent records a service. Check it is plausible: if the port is open, use run_nc once "
    "to read its banner and compare with the claimed service type. If the claimed service type is "
    "https or another TLS port and a plain run_nc call returns nothing, that is expected - retry once "
    "with tls set rather than repeating the same plain call. If it looks right, reply with one short "
    "sentence: confirmed. If something looks wrong - the banner doesn't match the claimed service, an "
    "open port doesn't answer at all, or anything else is off - first call publish_message with topic "
    "task.sinverguenza and a short message naming the host, the port, and exactly what looks wrong, so "
    "it gets investigated, then reply with one short sentence summarizing what you found."
)
"""The reviewer prompt as it stood before it took over service identification from discoverer -
frozen so the nmap-handoff backfill can tell an unedited install apart from a customized one."""
REVIEWER_PROMPT = load_prompt("reviewer")


LEGACY_REPORTER_PROMPT = (
    "You are a reporting agent inside a home-LAN monitoring platform. Call get_network_snapshot once to "
    "read the current state of every device, service, alert and network. Then write a clear Markdown "
    "report: a short summary first, then Networks, Devices, Services (group by host, mention product and "
    "version where known), Active alerts and Recommendations (down or degraded items, unmonitored "
    "discovered services, anything unusual). Use only facts from the snapshot; do not invent numbers. "
    "Finish by calling save_report with a title and the full Markdown, then reply with one sentence."
)
REPORTER_PROMPT_PRE_REVIEWER = LEGACY_REPORTER_PROMPT + (
    " If the message you were given is a result from another agent (topic result.bellaco, "
    "result.sinverguenza or result.maestro), do not describe the whole network: write a report titled "
    "after that agent that organises its findings by host and severity, keeps its evidence, and ends "
    "with the recommended actions. Only call get_network_snapshot if you need context about a device, "
    "and when you do, pass hosts set to exactly the host(s) that result is about - never the whole "
    "network for a single host's result. If that message is marked incomplete (the agent stopped at its "
    "iteration limit without a real conclusion), do not call get_network_snapshot and do not invent "
    "findings or guess which hosts were covered: write a short report stating plainly that the "
    "investigation of its targets (if any were given) did not complete, and recommend re-running it - "
    "for example with a higher iteration limit or a narrower target list."
)
LEGACY_REPORTER_PROMPT_WITH_MAESTRO = REPORTER_PROMPT_PRE_REVIEWER + (
    " If the message you were given is from topic result.reviewer, it is a quick sanity check, not an "
    "investigation: reply with one brief acknowledgement sentence and do not call save_report or "
    "get_network_snapshot either way - if it says the service is confirmed there is nothing to write "
    "up, and if it flags something wrong the reviewer has already escalated it to sinverguenza, whose "
    "own result (topic result.sinverguenza) is when a real report is warranted."
)
"""The reporter prompt as it stood before maestro was retired - frozen so the maestro-merge backfill
can tell an unedited install apart from one whose prompt a human already customized."""
LEGACY_REPORTER_PROMPT_PRE_DELTA = (
    "Write reports from network state. Call get_network_snapshot once, then write a Markdown report: "
    "summary, Networks, Devices, Services (grouped by host, with product/version), Active alerts, "
    "Recommendations. Use only snapshot facts - never invent numbers. Call save_report with a title "
    "and the Markdown, then reply with one sentence."
    " If the message is a result from bellaco or sinverguenza, write a report titled after that agent "
    "instead: organise by host and severity, keep its evidence, end with recommended actions. Only "
    "call get_network_snapshot for context on the host(s) that result names - never the whole network. "
    "If that result is marked incomplete (agent hit its iteration limit without concluding), skip "
    "get_network_snapshot and don't invent findings: state plainly the investigation didn't finish and "
    "recommend re-running it (higher iteration limit or narrower targets)."
    " If the message is from result.reviewer or result.discoverer, it's routine, not an investigation: "
    "reply with one brief acknowledgement, no save_report or get_network_snapshot - reviewer already "
    "escalates real problems to sinverguenza, whose result is when a report is warranted."
)
"""The reporter prompt as it stood before get_status_delta - frozen so the delta-reporting backfill
can tell an unedited install apart from one whose prompt a human already customized."""
REPORTER_PROMPT = load_prompt("reporter")
SECURITY_AGENT_NAMES = ("bellaco", "sinverguenza")
SECURITY_RESULT_TOPICS = [f"result.{name}" for name in SECURITY_AGENT_NAMES]

_INSPECTION_TOOLS = ["list_inspect_targets", "ssh_readonly", "winrm_readonly", "proxmox_get"]
_HOW_TO_INSPECT = (
    "Start with list_inspect_targets to see hosts and os_kind. Use ssh_readonly (linux), winrm_readonly "
    "(windows), proxmox_get (proxmox) - read-only commands only; a refusal explains why, so adjust. "
    "Commands are single words with options, no quotes/pipes/wildcards. Inspect only named hosts, else "
    "every target. Base statements only on tool output - never invent, and say when something couldn't "
    "be checked."
)
"""Shared fragment, inlined into the live bellaco.md/sinverguenza.md prompt files. Kept here as Python
too only because LEGACY_SINVERGUENZA_PROMPT below still composes with it and must stay frozen."""
BELLACO_PROMPT = load_prompt("bellaco")
LEGACY_SINVERGUENZA_PROMPT = (
    "You are Sinverguenza, a security-incident investigator inside a home-LAN monitoring platform. You "
    "cannot change anything. For linux look at logins (last, lastb, journalctl -u ssh, grep failed "
    "/var/log/auth.log), listening ports (ss -tulpn), unexpected processes (ps aux), accounts (getent "
    "passwd, grep for uid 0), scheduled jobs (crontab -l, ls /etc/cron.d), SSH keys (cat "
    "/home/<user>/.ssh/authorized_keys) and recently changed files (find /tmp /var/tmp -newer /etc/hostname "
    "-type f). For windows use Get-WinEvent -LogName Security -MaxEvents 100, Get-LocalUser, "
    "Get-LocalGroupMember -Group Administrators, Get-ScheduledTask, Get-NetTCPConnection and "
    "Get-MpThreatDetection. For proxmox read /nodes/<node>/tasks and /nodes/<node>/syslog and look for "
    "failed logins and unexpected tasks. For web services call http_inspect and report an expired or "
    "self-signed certificate, missing security headers and odd redirects. "
    + _HOW_TO_INSPECT
    + " Final answer: for each host, Verdict (suspicious, needs attention or no evidence found), the "
    "evidence quoted from tool output, your confidence, and what a human should check next. Do not "
    "speculate beyond the evidence."
)
# Absorbs Maestro's forensic scope (timeline, artifacts, hashing, VirusTotal) after that agent was
# retired - see docs/decisions.md. Deliberately simpler than concatenating both old prompts: one
# investigator, one job (find and publish), no report-writing of its own (that stays reporter's job).
SINVERGUENZA_PROMPT = load_prompt("sinverguenza")


def security_agents() -> list[AiAgent]:
    def agent(name: str, role: str, prompt: str, tools: list[str], iterations: int, **extra: bool) -> AiAgent:
        return AiAgent(
            name=name,
            role=role,
            system_prompt=prompt,
            temperature=0.2,
            max_iterations=iterations,
            enabled_tools=tools,
            subscribes=[f"task.{name}", f"human.{name}", "result.reviewer", "result.discoverer"],
            publishes=["result.#"],
            **extra,
        )

    return [
        agent(
            "bellaco",
            "Finds performance, update and health problems on hosts through their integrations",
            BELLACO_PROMPT,
            [
                *_INSPECTION_TOOLS,
                "get_network_snapshot",
                "apply_updates",
                "submit_http_form",
                "record_finding",
            ],
            20,
            allow_changes=True,
        ),
        agent(
            "sinverguenza",
            "Investigates security incidents on hosts, read-only; forensics and VirusTotal lookups included",
            SINVERGUENZA_PROMPT,
            [*_INSPECTION_TOOLS, "http_inspect", "submit_http_form", "record_finding"],
            45,  # a real investigation (list targets, http_inspect, ssh_readonly, file reads) ran past 25
        ),
    ]


REPORTER_TOOLS = ["get_status_delta", "save_report"]


async def ensure_default_telegram_config(session: AsyncSession) -> TelegramConfig:
    result = await session.execute(select(TelegramConfig).order_by(TelegramConfig.id).limit(1))
    config = result.scalar_one_or_none()
    if config is None:
        config = TelegramConfig()
        session.add(config)
        await session.commit()
        await session.refresh(config)
    return config


async def ensure_default_agents(session: AsyncSession) -> None:
    """Seeds the `discoverer` agent from the single-agent AI Mode settings (so an
    existing install keeps its prompt, model and tools), an example `reviewer`
    that listens for what the discoverer records, the `reporter` and the two
    security agents. An install that predates the security agents gets them once."""
    settings = await ensure_default_ai_mode_settings(session)
    changed = False
    if (await session.execute(select(AiAgent.id).limit(1))).first() is None:
        session.add_all(
            [
                AiAgent(
                    name="discoverer",
                    display_name="Master Discoverer",
                    role="Finds open ports on a host",
                    system_prompt=settings.system_prompt,
                    model_override=settings.model_override,
                    temperature=settings.temperature,
                    max_iterations=settings.max_iterations,
                    enabled_tools=list(settings.enabled_tools),
                    subscribes=["task.discoverer", "human.discoverer"],
                    publishes=["result.#"],
                ),
                AiAgent(
                    name="reviewer",
                    role="Identifies and records the services behind open ports",
                    system_prompt=REVIEWER_PROMPT,
                    temperature=0.2,
                    max_iterations=20,
                    enabled_tools=["run_nmap", "run_nc", "record_service", "publish_message"],
                    subscribes=["discovery.ports.found", "human.reviewer"],
                    publishes=["result.#", "task.sinverguenza"],
                ),
                reporter_agent(),
            ]
        )
        await session.flush()
        changed = True
    if not settings.security_agents_seeded:
        await _seed_security_agents(session)
        settings.security_agents_seeded = True
        changed = True
    if not settings.form_tool_seeded:
        await _seed_form_tool(session)
        settings.form_tool_seeded = True
        changed = True
    if not settings.reviewer_escalation_seeded:
        await _seed_reviewer_escalation(session)
        settings.reviewer_escalation_seeded = True
        changed = True
    if not settings.maestro_merged_into_sinverguenza:
        await _merge_maestro_into_sinverguenza(session)
        settings.maestro_merged_into_sinverguenza = True
        changed = True
    if not settings.reviewer_does_nmap_seeded:
        await _seed_reviewer_nmap_handoff(session)
        settings.reviewer_does_nmap_seeded = True
        changed = True
    if not settings.cross_agent_subscriptions_seeded:
        await _seed_cross_agent_subscriptions(session)
        settings.cross_agent_subscriptions_seeded = True
        changed = True
    if not settings.reporter_computes_deltas_seeded:
        await _seed_reporter_deltas(session)
        settings.reporter_computes_deltas_seeded = True
        changed = True
    if not settings.run_reports_seeded:
        await _seed_run_reports(session)
        settings.run_reports_seeded = True
        changed = True
    if not settings.tajonaso_seeded:
        await _seed_tajonaso(session)
        settings.tajonaso_seeded = True
        changed = True
    if changed:
        await session.commit()


async def _seed_tajonaso(session: AsyncSession) -> None:
    """Registers every HexStrike AI tool (scripts/hexstrike_tools.json, extracted from HexStrike's own
    @mcp.tool() signatures) as an AiCustomTool and creates the tajonaso agent with all of them enabled -
    runs once, same one-shot pattern as security_agents_seeded. Only tajonaso gets these tools; no other
    agent's enabled_tools is touched. A renamed or deleted tajonaso, or a tool an administrator already
    edited, is left alone on any later start, since this only ever runs the one time."""
    tools: list[dict[str, Any]] = json.loads(HEXSTRIKE_TOOLS_FILE.read_text())
    for spec in tools:
        existing = await session.scalar(select(AiCustomTool).where(AiCustomTool.name == spec["name"]))
        if existing is None:
            session.add(
                AiCustomTool(
                    name=spec["name"],
                    description=spec["description"],
                    kind="mcp",
                    mcp_url=HEXSTRIKE_MCP_URL,
                    mcp_tool=spec["name"],
                    parameters=spec["parameters"],
                )
            )
    if await session.scalar(select(AiAgent.id).where(AiAgent.name == "tajonaso")) is None:
        session.add(
            AiAgent(
                name="tajonaso",
                display_name="Tajonaso",
                role="Offensive security testing against the LAN via HexStrike AI",
                system_prompt=TAJONASO_PROMPT,
                provider="ollama",
                model_override="gpt-oss:20b",
                enabled_tools=[*(t["name"] for t in tools), "save_report"],
                mcp_url_override=HEXSTRIKE_MCP_URL,
                mcp_timeout_seconds=120.0,
                # Several HexStrike tools (a full port-range nmap scan, a wordlist-based brute-force
                # attempt) genuinely run past the 30s default.
                max_iterations=30,
                # 15 was too low: both measured runs hit the limit without concluding - same source.
                subscribes=[],
                publishes=[],
                require_approval="none",
            )
        )
    await session.flush()


_LEGACY_DISCOVERER_TOOLS = ["run_nmap", "run_nc", "record_service", "discover_hosts"]
"""discoverer's enabled_tools as AiModeSettings.enabled_tools used to default to - frozen so the
nmap-handoff backfill only grants report_open_ports to a discoverer still on that exact unedited
list, never to one an administrator has already customized (including one just seeded fresh from a
settings.enabled_tools an administrator had already changed before AI Mode was ever used)."""


async def _seed_reviewer_nmap_handoff(session: AsyncSession) -> None:
    """Deep service identification moved from discoverer to reviewer (see docs/decisions.md): runs
    once. reviewer additively gets run_nmap and record_service (never removed if already customized),
    its subscription moves from discovery.service.found to discovery.ports.found and its prompt and
    loop limit are upgraded only if neither was ever edited. discoverer additively gets
    report_open_ports, but only if its tool list still exactly matches the old stock default -
    otherwise it was already seeded with (or customized to) something else and is left alone; its
    prompt is not touched here either way, since DEFAULT_SYSTEM_PROMPT (llm/agent.py) already takes
    effect for any install that left discoverer's own prompt blank. A renamed or deleted agent is
    left alone, same as every other backfill in this file."""
    reviewer = await session.scalar(select(AiAgent).where(AiAgent.name == "reviewer"))
    if reviewer is not None:
        for tool in ("run_nmap", "record_service"):
            if tool not in reviewer.enabled_tools:
                reviewer.enabled_tools = [*reviewer.enabled_tools, tool]
        if reviewer.subscribes == ["discovery.service.found", "human.reviewer"]:
            reviewer.subscribes = ["discovery.ports.found", "human.reviewer"]
        if reviewer.system_prompt == LEGACY_REVIEWER_PROMPT_PRE_NMAP:
            reviewer.system_prompt = REVIEWER_PROMPT
        if reviewer.max_iterations == 6:
            reviewer.max_iterations = 20
    discoverer = await session.scalar(select(AiAgent).where(AiAgent.name == "discoverer"))
    if discoverer is not None and discoverer.enabled_tools == _LEGACY_DISCOVERER_TOOLS:
        discoverer.enabled_tools = [*discoverer.enabled_tools, "report_open_ports"]


async def _seed_cross_agent_subscriptions(session: AsyncSession) -> None:
    """bellaco and sinverguenza get result.reviewer and result.discoverer added to their
    subscriptions, and reporter gets result.discoverer, so the whole team reacts to a plain
    discovery/review pass rather than only an explicit task or reviewer's narrow escalation - added
    once, additively, same one-shot pattern as every other backfill in this file. A renamed/deleted
    agent or a subscription list already carrying the topic is left alone."""
    for name in SECURITY_AGENT_NAMES:
        agent = await session.scalar(select(AiAgent).where(AiAgent.name == name))
        if agent is not None:
            missing = [t for t in ("result.reviewer", "result.discoverer") if t not in agent.subscribes]
            if missing:
                agent.subscribes = [*agent.subscribes, *missing]
    reporter = await session.scalar(select(AiAgent).where(AiAgent.name == "reporter"))
    if reporter is not None and "result.discoverer" not in reporter.subscribes:
        reporter.subscribes = [*reporter.subscribes, "result.discoverer"]


async def _seed_reporter_deltas(session: AsyncSession) -> None:
    """reporter additively gets get_status_delta (never removed if already customized) and its prompt
    is upgraded to use it - and to condense every agent-topic result into a real report instead of
    acknowledging a routine reviewer/discoverer pass without saving one - only if its prompt was never
    edited. Added once, same one-shot pattern as every other backfill in this file."""
    reporter = await session.scalar(select(AiAgent).where(AiAgent.name == "reporter"))
    if reporter is not None:
        if "get_status_delta" not in reporter.enabled_tools:
            reporter.enabled_tools = [*reporter.enabled_tools, "get_status_delta"]
        if reporter.system_prompt == LEGACY_REPORTER_PROMPT_PRE_DELTA:
            reporter.system_prompt = REPORTER_PROMPT


PRE_RUN_REPORT_PROMPT_HASHES = {
    "bellaco": "0d6c06697d33c186",
    "sinverguenza": "cad9ec1c2324ddf3",
    "reporter": "61c3f4ec24d52019",
}
"""sha256 prefixes of the stock prompts before per-network run reports, so the backfill can tell an
unedited install from a customized one without carrying a second copy of each prompt."""


async def _seed_run_reports(session: AsyncSession) -> None:
    """bellaco and sinverguenza additively get record_finding, and bellaco, sinverguenza and reporter get
    the prompts that use it, only if the prompt was never edited. Added once, same one-shot pattern as
    every other backfill in this file."""
    for name in (*SECURITY_AGENT_NAMES, "reporter"):
        agent = await session.scalar(select(AiAgent).where(AiAgent.name == name))
        if agent is None:
            continue
        if name != "reporter" and "record_finding" not in agent.enabled_tools:
            agent.enabled_tools = [*agent.enabled_tools, "record_finding"]
        digest = hashlib.sha256(agent.system_prompt.encode()).hexdigest()[:16]
        if digest == PRE_RUN_REPORT_PROMPT_HASHES[name]:
            agent.system_prompt = load_prompt(name)


async def _merge_maestro_into_sinverguenza(session: AsyncSession) -> None:
    """Maestro was retired - its forensic/VirusTotal role is now sinverguenza's job (see
    docs/decisions.md). Runs once: deletes the maestro agent if it exists, carries over its
    virustotal_lookup permission onto sinverguenza if it had been enabled there (an install that
    never opted maestro into VirusTotal does not get it switched on for sinverguenza either - still
    opt-in), updates sinverguenza's and reporter's prompts only where neither was ever edited, and
    drops the now-dead result.maestro topic from reporter's subscriptions."""
    maestro = await session.scalar(select(AiAgent).where(AiAgent.name == "maestro"))
    if maestro is not None:
        if "virustotal_lookup" in maestro.enabled_tools:
            sinverguenza = await session.scalar(select(AiAgent).where(AiAgent.name == "sinverguenza"))
            if sinverguenza is not None and "virustotal_lookup" not in sinverguenza.enabled_tools:
                sinverguenza.enabled_tools = [*sinverguenza.enabled_tools, "virustotal_lookup"]
        await session.delete(maestro)
    sinverguenza = await session.scalar(select(AiAgent).where(AiAgent.name == "sinverguenza"))
    if sinverguenza is not None and sinverguenza.system_prompt == LEGACY_SINVERGUENZA_PROMPT:
        sinverguenza.system_prompt = SINVERGUENZA_PROMPT
    reporter = await session.scalar(select(AiAgent).where(AiAgent.name == "reporter"))
    if reporter is not None:
        if "result.maestro" in reporter.subscribes:
            reporter.subscribes = [t for t in reporter.subscribes if t != "result.maestro"]
        if reporter.system_prompt == LEGACY_REPORTER_PROMPT_WITH_MAESTRO:
            reporter.system_prompt = REPORTER_PROMPT


async def _seed_reviewer_escalation(session: AsyncSession) -> None:
    """reviewer gets permission (publishes + the publish_message tool) to hand a bad finding to
    sinverguenza instead of it being a dead end, and reporter learns to acknowledge a reviewer
    sanity-check without writing a report for it - added once; a renamed/deleted agent or an
    already-edited prompt is left alone, same as _seed_security_agents."""
    reviewer = await session.scalar(select(AiAgent).where(AiAgent.name == "reviewer"))
    if reviewer is not None:
        if "task.sinverguenza" not in reviewer.publishes:
            reviewer.publishes = [*reviewer.publishes, "task.sinverguenza"]
        if "publish_message" not in reviewer.enabled_tools:
            reviewer.enabled_tools = [*reviewer.enabled_tools, "publish_message"]
        if reviewer.system_prompt == LEGACY_REVIEWER_PROMPT:
            reviewer.system_prompt = REVIEWER_PROMPT
    reporter = await session.scalar(select(AiAgent).where(AiAgent.name == "reporter"))
    if reporter is not None:
        if "result.reviewer" not in reporter.subscribes:
            reporter.subscribes = [*reporter.subscribes, "result.reviewer"]
        if reporter.system_prompt == REPORTER_PROMPT_PRE_REVIEWER:
            reporter.system_prompt = REPORTER_PROMPT


async def _seed_form_tool(session: AsyncSession) -> None:
    """submit_http_form is added to each stock security agent's tool list once (bellaco/sinverguenza,
    or bellaco/sinverguenza/maestro on an install from before maestro was retired, since this already
    ran by the time that merge happens) - an install that predates the tool gets it added if the agent
    still exists and doesn't already have it; a renamed, deleted, or already-edited agent is left
    alone, same as _seed_security_agents."""
    agents = list(await session.scalars(select(AiAgent).where(AiAgent.name.in_(SECURITY_AGENT_NAMES))))
    for agent in agents:
        if "submit_http_form" not in agent.enabled_tools:
            agent.enabled_tools = [*agent.enabled_tools, "submit_http_form"]


async def _seed_security_agents(session: AsyncSession) -> None:
    taken = set(await session.scalars(select(AiAgent.name)))
    session.add_all(a for a in security_agents() if a.name not in taken)
    reporter = await session.scalar(select(AiAgent).where(AiAgent.name == "reporter"))
    if reporter is None:
        return
    missing = [t for t in SECURITY_RESULT_TOPICS if t not in reporter.subscribes]
    reporter.subscribes = [*reporter.subscribes, *missing]
    if reporter.system_prompt == LEGACY_REPORTER_PROMPT:
        reporter.system_prompt = REPORTER_PROMPT  # only an unedited prompt is replaced


def reporter_agent() -> AiAgent:
    return AiAgent(
        name="reporter",
        role="Writes reports of the network and its services",
        system_prompt=REPORTER_PROMPT,
        temperature=0.2,
        max_iterations=6,
        enabled_tools=list(REPORTER_TOOLS),
        subscribes=[
            "task.reporter", "human.reporter", "result.reviewer", "result.discoverer",
            *SECURITY_RESULT_TOPICS,
        ],
        publishes=["result.#"],
    )
