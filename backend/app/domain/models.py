import datetime
import enum
from typing import Any

from sqlalchemy import JSON, ForeignKey, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import get_settings
from app.domain.enums import (
    AlertConditionType,
    AlertSeverity,
    AlertState,
    AssistantMessageRole,
    AssistantProvider,
    CandidateStatus,
    CandidateType,
    DeviceType,
    EntityType,
    EventSeverity,
    HealthStatus,
    IntegrationStatus,
    NotificationChannelType,
    ServiceType,
)
from app.domain.types import UTCDateTime


class Base(DeclarativeBase):
    pass


def sa_enum(enum_cls: type[enum.Enum]) -> SAEnum:
    return SAEnum(enum_cls, values_callable=lambda e: [member.value for member in e], native_enum=False)


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class TimestampMixin:
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class Site(Base, TimestampMixin):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None]

    networks: Mapped[list["Network"]] = relationship(back_populates="site")
    devices: Mapped[list["Device"]] = relationship(back_populates="site")


class Network(Base, TimestampMixin):
    __tablename__ = "networks"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    name: Mapped[str]
    cidr: Mapped[str]
    vlan_id: Mapped[int | None]
    description: Mapped[str | None]

    site: Mapped[Site] = relationship(back_populates="networks")
    devices: Mapped[list["Device"]] = relationship(back_populates="network")
    credential_bindings: Mapped[list["NetworkCredentialBinding"]] = relationship(
        back_populates="network", order_by="NetworkCredentialBinding.priority", cascade="all, delete-orphan"
    )


class NetworkCredentialBinding(Base):
    """An ordered credential this network's discovery scan should try against
    any host it finds with SSH open - see docs/decisions.md "Auto-login on
    discovery". `credential_id` is an opaque reference into credentials.db,
    the same convention `Integration.credential_id` already uses; nothing
    here can join to the secret payload itself."""

    __tablename__ = "network_credential_bindings"
    __table_args__ = (UniqueConstraint("network_id", "credential_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    network_id: Mapped[int] = mapped_column(ForeignKey("networks.id"))
    credential_id: Mapped[int]
    priority: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)

    network: Mapped[Network] = relationship(back_populates="credential_bindings")


class Device(Base, TimestampMixin):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    network_id: Mapped[int | None] = mapped_column(ForeignKey("networks.id"))
    hostname: Mapped[str | None]
    hostname_source: Mapped[str | None] = mapped_column(default=None)
    """Where `hostname` came from: manual, ssh, dns, mdns, netbios or tls (discovery/hostnames.py)."""
    display_name: Mapped[str]
    primary_ip: Mapped[str | None]
    device_type: Mapped[DeviceType] = mapped_column(sa_enum(DeviceType))
    status: Mapped[HealthStatus] = mapped_column(sa_enum(HealthStatus), default=HealthStatus.UNKNOWN)
    first_seen_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_seen_at: Mapped[datetime.datetime | None] = mapped_column(UTCDateTime())
    managed: Mapped[bool] = mapped_column(default=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str | None]

    site: Mapped[Site] = relationship(back_populates="devices")
    network: Mapped[Network | None] = relationship(back_populates="devices")
    addresses: Mapped[list["DeviceAddress"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )
    services: Mapped[list["Service"]] = relationship(back_populates="device")


class DeviceAddress(Base):
    __tablename__ = "device_addresses"
    __table_args__ = (UniqueConstraint("device_id", "ip_address"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"))
    ip_address: Mapped[str]
    mac_address: Mapped[str | None]
    is_primary: Mapped[bool] = mapped_column(default=False)

    device: Mapped[Device] = relationship(back_populates="addresses")


class Service(Base, TimestampMixin):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"))
    name: Mapped[str]
    service_type: Mapped[ServiceType] = mapped_column(sa_enum(ServiceType))
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[HealthStatus] = mapped_column(sa_enum(HealthStatus), default=HealthStatus.UNKNOWN)
    last_checked_at: Mapped[datetime.datetime | None] = mapped_column(UTCDateTime())
    managed: Mapped[bool] = mapped_column(default=True)
    port: Mapped[int | None] = mapped_column(default=None)
    source: Mapped[str] = mapped_column(default="manual", server_default="manual")
    """'manual' | 'scan' | 'ai' - how the row came to exist."""
    fingerprint: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    """nmap/AI service identification: name, product, version, extrainfo, banner, fingerprinted_at."""

    device: Mapped[Device | None] = relationship(back_populates="services")


class Integration(Base, TimestampMixin):
    __tablename__ = "integrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    integration_type: Mapped[str]
    name: Mapped[str]
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    credential_id: Mapped[int | None]
    enabled: Mapped[bool] = mapped_column(default=True)
    status: Mapped[IntegrationStatus] = mapped_column(
        sa_enum(IntegrationStatus), default=IntegrationStatus.UNKNOWN
    )
    last_run_at: Mapped[datetime.datetime | None] = mapped_column(UTCDateTime())
    last_error: Mapped[str | None]

    targets: Mapped[list["IntegrationTarget"]] = relationship(
        back_populates="integration", cascade="all, delete-orphan"
    )


class IntegrationTarget(Base):
    __tablename__ = "integration_targets"
    __table_args__ = (UniqueConstraint("integration_id", "external_ref"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    integration_id: Mapped[int] = mapped_column(ForeignKey("integrations.id"))
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"))
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id"))
    external_ref: Mapped[str]
    discovered_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)

    integration: Mapped[Integration] = relationship(back_populates="targets")


class AlertRule(Base, TimestampMixin):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    condition_type: Mapped[AlertConditionType] = mapped_column(sa_enum(AlertConditionType))
    entity_selector: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    severity: Mapped[AlertSeverity] = mapped_column(sa_enum(AlertSeverity), default=AlertSeverity.WARNING)
    enabled: Mapped[bool] = mapped_column(default=True)
    flap_dampening: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AlertStateRow(Base):
    __tablename__ = "alert_states"
    __table_args__ = (UniqueConstraint("alert_rule_id", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_rule_id: Mapped[int] = mapped_column(ForeignKey("alert_rules.id"))
    entity_type: Mapped[EntityType] = mapped_column(sa_enum(EntityType))
    entity_id: Mapped[int]
    state: Mapped[AlertState] = mapped_column(sa_enum(AlertState), default=AlertState.OK)
    state_changed_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_evaluated_at: Mapped[datetime.datetime | None] = mapped_column(UTCDateTime())
    current_value: Mapped[float | None]
    consecutive_breach_count: Mapped[int] = mapped_column(default=0)
    flap_score: Mapped[float] = mapped_column(default=0.0)

    rule: Mapped[AlertRule] = relationship()
    transitions: Mapped[list["AlertEvent"]] = relationship(
        back_populates="alert_state", cascade="all, delete-orphan"
    )


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_state_id: Mapped[int] = mapped_column(ForeignKey("alert_states.id"))
    from_state: Mapped[AlertState] = mapped_column(sa_enum(AlertState))
    to_state: Mapped[AlertState] = mapped_column(sa_enum(AlertState))
    ts: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    value_at_transition: Mapped[float | None]
    message: Mapped[str | None]

    alert_state: Mapped[AlertStateRow] = relationship(back_populates="transitions")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    source: Mapped[str]
    severity: Mapped[EventSeverity] = mapped_column(sa_enum(EventSeverity), default=EventSeverity.INFO)
    category: Mapped[str]
    message: Mapped[str]
    related_entity_type: Mapped[EntityType | None] = mapped_column(sa_enum(EntityType))
    related_entity_id: Mapped[int | None]


class DiscoveredCandidate(Base):
    __tablename__ = "discovered_candidates"
    __table_args__ = (UniqueConstraint("candidate_type", "fingerprint"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_type: Mapped[CandidateType] = mapped_column(sa_enum(CandidateType))
    fingerprint: Mapped[str]
    """Dedup key: MAC (preferred) or IP for devices, 'ip:port:protocol' for services."""
    discovered_via: Mapped[str]
    network_id: Mapped[int | None] = mapped_column(ForeignKey("networks.id"))
    raw_attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    first_seen_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_seen_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    times_seen: Mapped[int] = mapped_column(default=1)
    status: Mapped[CandidateStatus] = mapped_column(sa_enum(CandidateStatus), default=CandidateStatus.PENDING)
    resulting_device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"))
    resulting_service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id"))


class NotificationChannel(Base):
    __tablename__ = "notification_channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_type: Mapped[NotificationChannelType] = mapped_column(sa_enum(NotificationChannelType))
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(default=True)


class AssistantConfig(Base, TimestampMixin):
    """Singleton settings row for the chat assistant - see
    bootstrap.ensure_default_assistant_config. credential_id is an opaque
    reference into credentials.db, same convention as Integration.credential_id."""

    __tablename__ = "assistant_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[AssistantProvider] = mapped_column(
        sa_enum(AssistantProvider), default=AssistantProvider.OLLAMA
    )
    base_url: Mapped[str] = mapped_column(default=lambda: get_settings().ollama_base_url)
    model: Mapped[str] = mapped_column(default=lambda: get_settings().ollama_model)
    credential_id: Mapped[int | None] = mapped_column(default=None)
    max_tool_iterations: Mapped[int] = mapped_column(default=8)
    """Model round trips (each may call tools) allowed for one chat turn."""
    llm_timeout_seconds: Mapped[float] = mapped_column(default=120.0)
    """How long one model call may take before the turn fails; raise it for a slow model."""
    full_access: Mapped[bool] = mapped_column(default=False)
    """Off (default): the assistant only sees the read tools (llm/tools.py's READ_TOOL_NAMES) - no
    write tool is even offered to the model. On ("god mode"): every curated tool is offered, including
    the safe-write set. Either way, enforced server-side in dispatch_tool_call, not just by hiding the
    tool schema - a model that tries a write tool anyway while this is off gets a refusal, same
    guardrail-can't-be-prompted-around philosophy as AI Mode's own tool gates. Deletes and
    credential/integration mutation remain absent from the tool list regardless of this setting - that
    boundary is not configurable."""


class AssistantMessage(Base):
    """Flat, global chat timeline - same shape as Event, no session/thread
    concept (this is a single-tenant, no-auth app). tool_calls is populated
    only on assistant rows, purely for transparent transcript display; it is
    not replayed back to the LLM as context on later turns (see llm/service.py)."""

    __tablename__ = "assistant_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    role: Mapped[AssistantMessageRole] = mapped_column(sa_enum(AssistantMessageRole))
    content: Mapped[str]
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, default=None)


class DiscoverySettings(Base, TimestampMixin):
    """Singleton settings row for nmap-based discovery and AI Mode - see
    bootstrap.ensure_default_discovery_settings."""

    __tablename__ = "discovery_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    nmap_enabled: Mapped[bool] = mapped_column(default=True)
    scan_mode: Mapped[str] = mapped_column(default="auto")
    """'manual' | 'auto'"""
    auto_interval_seconds: Mapped[int] = mapped_column(default=1800)
    timing_template: Mapped[int] = mapped_column(default=4)
    """nmap -T0..-T5; default 4 (aggressive)."""
    host_timeout_seconds: Mapped[int] = mapped_column(default=30)
    max_retries: Mapped[int] = mapped_column(default=1)
    version_intensity: Mapped[int] = mapped_column(default=2)
    ai_mode_enabled: Mapped[bool] = mapped_column(default=False)
    agent_internet_blocked: Mapped[bool] = mapped_column(default=False)
    """Kill switch: while set, agents' web tools refuse every call. Only a human sets it, through the
    system settings API; no agent tool can read or write it."""
    max_db_size_mb: Mapped[int] = mapped_column(default=512)
    """Size cap for metrics.db; oldest samples are trimmed past it (metrics/rollup.py)."""
    dns_server: Mapped[str] = mapped_column(default="")
    """DNS server asked for host names (reverse lookups) during discovery; empty = the system resolver."""
    auto_accept_services: Mapped[bool] = mapped_column(default=False)
    """A newly seen service candidate is accepted and monitored at once instead of waiting for review."""
    ssh_hostkey_approval: Mapped[bool] = mapped_column(default=True)
    """Auto-login sends no password to a host whose SSH key a human has not approved. Off on installs that
    already used auto-login before this existed (the migration), on for new ones."""
    ssh_hostkey_auto_repin: Mapped[bool] = mapped_column(default=True)
    """A known host presenting a *different* SSH key is re-pinned automatically instead of pausing
    auto-login for re-approval - on by default since a home LAN routinely reassigns an IP to a new
    machine (reimage, new VM). Off restores strict pinning: any key change pauses, same as an
    unapproved key."""


class AiModeSettings(Base, TimestampMixin):
    """Singleton: everything about the AI Mode agent a human may tune. The
    safety guardrails (CIDR restriction, nmap flag allowlist, no shell) are
    deliberately NOT here - see llm/agent_tools.py."""

    __tablename__ = "ai_mode_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    system_prompt: Mapped[str] = mapped_column(default="")
    """Empty means: use llm.agent.DEFAULT_SYSTEM_PROMPT."""
    model_override: Mapped[str] = mapped_column(default="")
    """Empty means: use `llm_model`."""
    llm_base_url: Mapped[str] = mapped_column(default=lambda: get_settings().ollama_base_url)
    llm_model: Mapped[str] = mapped_column(default=lambda: get_settings().ollama_model)
    """The host and model agents use unless an agent sets its own. Separate from the chat assistant."""
    llm_provider: Mapped[AssistantProvider] = mapped_column(
        sa_enum(AssistantProvider), default=AssistantProvider.OLLAMA
    )
    llm_credential_id: Mapped[int | None] = mapped_column(default=None)
    """OpenRouter API key (an opaque reference into credentials.db); unused for Ollama."""
    usage_reset_at: Mapped[datetime.datetime | None] = mapped_column(UTCDateTime(), default=None)
    """When the token counters (LlmUsage) were last reset; None if never."""
    cost_budget_usd: Mapped[float | None] = mapped_column(default=None)
    """None/0 means no budget. Alert-only (see docs/decisions.md): crossing it never blocks a run,
    it only pushes one Telegram notification (api.ai_cost, app.llm.usage.check_cost_budget)."""
    cost_budget_alert_sent: Mapped[bool] = mapped_column(default=False)
    """Set once the budget is crossed, so the notification fires only once per period - cleared by
    resetting the usage counters or by changing the budget itself."""
    max_iterations: Mapped[int] = mapped_column(default=30)
    """A multi-host LAN scan (discoverer's own use of this) easily needs more than a few
    model-call turns; 15 was observed cutting a 7-host scan off before it finished."""
    temperature: Mapped[float] = mapped_column(default=0.2)
    max_targets: Mapped[int] = mapped_column(default=25)
    enabled_tools: Mapped[list[str]] = mapped_column(
        JSON, default=lambda: ["run_nmap", "run_nc", "report_open_ports", "discover_hosts"]
    )
    max_run_minutes: Mapped[int] = mapped_column(default=30)
    """Every run (manual or scheduled) is stopped automatically after this long."""
    llm_call_timeout_seconds: Mapped[float] = mapped_column(default=120.0)
    """How long a single model call may take before it's treated as failed. Self-hosted Ollama on
    modest hardware can need more than the default; raise it rather than the call just failing."""
    schedule_enabled: Mapped[bool] = mapped_column(default=False)
    schedule_interval_seconds: Mapped[int] = mapped_column(default=21600)
    """Start a run this long after the previous scheduled one started - the knob that turns this into
    a continuous loop (set it low) or an occasional sweep (set it high); `max_run_minutes`/`max_targets`
    below are what keep a tight loop from running away with LLM calls or host load."""
    schedule_entry_agent: Mapped[str] = mapped_column(default="discoverer")
    last_scheduled_at: Mapped[datetime.datetime | None] = mapped_column(UTCDateTime())
    security_agents_seeded: Mapped[bool] = mapped_column(default=False)
    """Bellaco, Sinverguenza and Maestro are added once, so deleting one is permanent."""
    schedule_cursor: Mapped[int] = mapped_column(default=0)
    """Highest device id handed to a scheduled run, so successive runs rotate through every device."""
    allow_undefined_network_scan: Mapped[bool] = mapped_column(default=False)
    """Lets discover_hosts (llm/agent_tools.py) sweep a CIDR outside every configured Network, as long
    as it is entirely inside RFC1918 private space. Off by default: scanning is otherwise always
    confined to networks an administrator explicitly registered."""
    undefined_scan_max_hosts: Mapped[int] = mapped_column(default=256)
    """Host-count cap for one of those out-of-network sweeps - deliberately smaller than
    network_scanner.MAX_HOSTS_PER_SCAN (1024), since this range was never vetted by an administrator."""
    allow_public_targets: Mapped[bool] = mapped_column(default=False)
    """A further, more dangerous relaxation on top of allow_undefined_network_scan: lets a single-target
    tool (run_nmap/run_nc/record_service/report_open_ports/submit_http_form, and a custom tool's
    target/ip/host) be pointed at a publicly routable address, not just a private one - this is attack
    surface on someone else's network, so it requires an explicit, disclaimed opt-in. Both switches must
    be on; off by default. Deliberately does NOT extend to discover_hosts - sweeping a public CIDR is a
    mass-scanning capability this setting is not meant to grant."""
    cred_allow_unlisted_hosts: Mapped[bool] = mapped_column(default=False)
    """Credential-pool safeguard (llm/credential_pool.py): off confines credential tries to loopback, a
    configured Network or a known Device. On: any private address. Public addresses additionally need
    allow_undefined_network_scan and allow_public_targets, whatever this says."""
    cred_no_attempt_limit: Mapped[bool] = mapped_column(default=False)
    """Safeguard: off caps tries at credential_pool.MAX_ATTEMPTS_PER_HOST per host per window (lockouts)."""
    cred_trust_new_host_keys: Mapped[bool] = mapped_column(default=False)
    """Safeguard: off means a pool credential is only sent to an SSH host whose key was approved/pinned.
    On: an unseen key is trusted on first use, so a password goes out before the host is verified."""
    cred_pool_for_updates: Mapped[bool] = mapped_column(default=False)
    """Safeguard: off keeps apply_updates to host-bound or explicitly selected credentials."""
    ollama_max_concurrent_calls: Mapped[int] = mapped_column(default=2)
    """Caps in-flight model calls to an Ollama host across every agent in a run at once - a single
    consumer GPU serializes requests anyway, and more in-flight calls just means longer waits per call
    and a higher chance of a hang under load."""
    openrouter_max_concurrent_calls: Mapped[int] = mapped_column(default=4)
    """Same cap for OpenRouter - a hosted API that can sustain more concurrent requests than a home GPU."""
    form_tool_seeded: Mapped[bool] = mapped_column(default=False)
    """submit_http_form is added to bellaco/sinverguenza/maestro's tool list once, so removing it
    afterward stays removed - same one-shot pattern as security_agents_seeded."""
    reviewer_escalation_seeded: Mapped[bool] = mapped_column(default=False)
    """reviewer gets permission to hand a bad finding to sinverguenza, and reporter learns to
    acknowledge a reviewer sanity-check without writing a report for it - added once, so removing
    either afterward stays removed - same one-shot pattern as security_agents_seeded."""
    maestro_merged_into_sinverguenza: Mapped[bool] = mapped_column(default=False)
    """Maestro (forensics/VirusTotal) was retired in favor of sinverguenza absorbing that role - the
    maestro agent is deleted once, its virustotal_lookup permission carried over to sinverguenza if it
    had been enabled, and sinverguenza's prompt updated unless it was already edited - same one-shot
    pattern as security_agents_seeded."""
    reviewer_does_nmap_seeded: Mapped[bool] = mapped_column(default=False)
    """Deep service identification (nmap -sV) moved from discoverer to reviewer, which now also
    calls record_service itself - reviewer gets run_nmap/record_service and the new discovery.ports.found
    subscription once, same one-shot pattern as security_agents_seeded."""
    cross_agent_subscriptions_seeded: Mapped[bool] = mapped_column(default=False)
    """bellaco and sinverguenza get result.reviewer and result.discoverer added to their subscriptions,
    and reporter gets result.discoverer, so the whole team reacts to a plain discovery/review pass and
    not just an explicit task or an escalation - added once, same one-shot pattern as
    security_agents_seeded."""
    performance_reset_at: Mapped[datetime.datetime | None] = mapped_column(UTCDateTime(), default=None)
    """When the Performance tab's "Reset" button was last pressed; None if never. Unlike usage_reset_at,
    this never deletes anything - llm/performance.py just ignores AiRunStep rows older than this, so
    Run History keeps every trace regardless."""
    reporter_computes_deltas_seeded: Mapped[bool] = mapped_column(default=False)
    """reporter gets get_status_delta added to its tools once, and its prompt upgraded to use it (and
    to condense every agent-topic result into a real report instead of just acknowledging a routine
    reviewer/discoverer pass) if its prompt was never edited - same one-shot pattern as
    security_agents_seeded."""
    run_reports_seeded: Mapped[bool] = mapped_column(default=False)
    """bellaco and sinverguenza get record_finding added to their tools once, and bellaco, sinverguenza and
    reporter have their prompts upgraded for per-network run reports if never edited - same one-shot
    pattern as security_agents_seeded."""
    tajonaso_seeded: Mapped[bool] = mapped_column(default=False)
    """The tajonaso agent and its ~150 HexStrike AI custom tools are created once from
    scripts/hexstrike_tools.json - same one-shot pattern as security_agents_seeded. A renamed or
    deleted tajonaso, or a tool an administrator already edited, is left alone on any later start."""
    knowledge_base_enabled: Mapped[bool] = mapped_column(default=False)
    """Master switch for the embedded agent knowledge base (knowledge.db): off by default, same role
    as DiscoverySettings.agent_internet_blocked but inverted (that one is a kill switch that defaults
    permissive; this one is a feature switch that defaults off). Checked in llm/agent_tools.dispatch()
    before search_knowledge/add_knowledge_entry run, regardless of an agent's own enabled_tools."""
    knowledge_embedding_base_url: Mapped[str] = mapped_column(default="")
    """Empty means: use llm_base_url (the same Ollama-compatible host agents already call for chat).
    Set this only when embeddings should come from a different host/provider than chat does."""
    knowledge_embedding_model: Mapped[str] = mapped_column(default="nomic-embed-text")
    knowledge_embedding_credential_id: Mapped[int | None] = mapped_column(default=None)
    """An API key credential for the embedding host, same credential store as llm_credential_id.
    Empty/None means no Authorization header is sent - fine for a local Ollama host, but a
    credentialed embedding provider (e.g. pointing this at OpenRouter) needs one set or every call
    401s. Not an OpenRouter-only field despite sharing that credential store: any OpenAI-compatible
    /embeddings endpoint that needs a bearer token uses this the same way."""
    knowledge_collections_seeded: Mapped[bool] = mapped_column(default=False)
    """The default collections (LAN notes, Security knowledge, Sandbox) are created once - same
    one-shot pattern as security_agents_seeded. A renamed or deleted collection is left alone."""
    memory_max_entries_per_agent: Mapped[int] = mapped_column(default=50)
    """Default cap on `remember` notes kept per agent (oldest pruned first); an agent's own
    memory_max_entries_override (AiAgent) replaces this for that agent when non-zero. Anchored
    to 2x AiModeSettings.max_targets (default 25 - how many devices one scheduled run sweeps),
    so memory survives roughly two full scheduled cycles before the oldest notes are pruned -
    see docs/decisions.md."""
    memory_max_content_chars: Mapped[int] = mapped_column(default=200)
    """Default per-note truncation length (~50 tokens): a `remember` note is meant to be one
    short fact, not a paragraph - see docs/ai-cost-and-models.md's "Agent memory" section for the
    reasoning (not yet a measured value, a judgement call sized to the tool's own intent). An
    agent's own memory_max_content_chars_override (AiAgent) replaces this for that agent when
    non-zero."""
    memory_max_inject_chars: Mapped[int] = mapped_column(default=4000)
    """Default total budget of saved-note content injected into an agent's system prompt per
    message (replaces a fixed note-count limit) - the actual context-window cost of memory.
    ~1000 tokens, sized to fit about 20 notes at the default per-note length above - raised in
    proportion to memory_max_entries_per_agent's anchor to max_targets, so a larger retained
    history is matched by a proportionally larger (not fixed) share actually reaching the model
    - while staying under 2% of the 64k num_ctx this project runs production models at (see
    docs/ai-cost-and-models.md) - still a judgement call, not yet a measured one. An agent's own
    memory_max_inject_chars_override (AiAgent) replaces this when non-zero. The UI shows all
    three memory size settings as an approximate token count (~4 chars/token); this column itself
    stays in characters - see docs/decisions.md."""


class AiCustomTool(Base, TimestampMixin):
    """A user-defined tool the AI Mode agent may call: a local command (argv
    template, no shell) or an MCP server tool reached over HTTP. Built-in
    tools stay in code (llm/agent_tools.py)."""

    __tablename__ = "ai_custom_tools"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str]
    kind: Mapped[str]
    """'command' | 'mcp'"""
    command: Mapped[list[str]] = mapped_column(JSON, default=list)
    """argv template for kind=command; {target} and {port} are substituted."""
    mcp_url: Mapped[str | None]
    mcp_tool: Mapped[str | None]
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    """JSON schema shown to the model."""
    enabled: Mapped[bool] = mapped_column(default=True)
    mcp_server_id: Mapped[int | None] = mapped_column(default=None)
    """The AiMcpServer this tool was imported from; None for hand-made tools. Not a foreign key: they are
    not enforced on pooled connections, so deleting a server removes its tools explicitly."""


class AiMcpServer(Base, TimestampMixin):
    """An MCP server whose tools are imported as AiCustomTool rows, so they can be tested, refreshed and
    removed together. Same minimal client as every MCP tool: streamable HTTP, no authentication."""

    __tablename__ = "ai_mcp_servers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    url: Mapped[str]


class AiGuardrail(Base, TimestampMixin):
    """A user-defined rule checked against every argument value a tool receives: deny_regex blocks on a
    match, allow_regex blocks on a non-match. Which tools it covers is `applies_to`."""

    __tablename__ = "ai_guardrails"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    description: Mapped[str] = mapped_column(default="")
    kind: Mapped[str]
    """'deny_regex' | 'allow_regex'"""
    pattern: Mapped[str]
    enabled: Mapped[bool] = mapped_column(default=True)
    applies_to: Mapped[str] = mapped_column(default="default", server_default="default")
    """'default' (custom tools and host-inspection tools) | 'all' (every tool). See llm/guardrail_scope.py."""


class AiRun(Base):
    __tablename__ = "ai_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(default="running")
    """running | done | error"""
    targets: Mapped[list[str]] = mapped_column(JSON, default=list)
    dry_run: Mapped[bool] = mapped_column(default=False)
    model: Mapped[str] = mapped_column(default="")
    base_url: Mapped[str] = mapped_column(default="")
    system_prompt: Mapped[str] = mapped_column(default="")
    settings_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[str | None]
    error: Mapped[str | None]
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
    started_by: Mapped[str] = mapped_column(default="manual")
    """manual | schedule"""
    stop_reason: Mapped[str | None]
    """manual (a human stopped it) | time_limit (stopped automatically); empty when it finished by itself."""


class AiRunStep(Base):
    """One thing that happened in a run: `llm` (a model round trip) or `tool`
    (a tool the model asked for). Stored in full so the UI can teach what the
    agent saw, decided and did."""

    __tablename__ = "ai_run_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("ai_runs.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int]
    ts: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    kind: Mapped[str]
    """llm | tool | error"""
    name: Mapped[str | None]
    """tool name for kind=tool"""
    request: Mapped[Any] = mapped_column(JSON, default=None)
    """llm: messages sent (truncated). tool: arguments."""
    response: Mapped[Any] = mapped_column(JSON, default=None)
    """llm: {content, reasoning, tool_calls}. tool: result."""
    duration_ms: Mapped[int] = mapped_column(default=0)
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
    agent: Mapped[str | None] = mapped_column(default=None)
    """Which agent produced this step."""


class LlmUsage(Base):
    """Token counts for model calls, one row per day, source, agent, provider and model (llm/usage.py)."""

    __tablename__ = "llm_usage"
    __table_args__ = (UniqueConstraint("day", "source", "agent", "provider", "model"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[str] = mapped_column(index=True)
    """UTC date, YYYY-MM-DD."""
    source: Mapped[str]
    """agent | assistant."""
    agent: Mapped[str]
    """The agent's name, or 'chat' for the chat assistant."""
    provider: Mapped[str]
    model: Mapped[str]
    calls: Mapped[int] = mapped_column(default=0)
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
    max_context_tokens: Mapped[int] = mapped_column(default=0)
    """Largest single call: prompt plus completion tokens."""
    calls_without_usage: Mapped[int] = mapped_column(default=0)
    """Calls whose reply carried no token counts, so they are in `calls` but add no tokens."""


class AiAgent(Base, TimestampMixin):
    """One configurable agent. Agents never call each other directly: they
    subscribe to topics on the message bus and publish to topics (llm/bus.py)."""

    __tablename__ = "ai_agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    """Stable identifier - referenced as a default elsewhere (schedule_entry_agent, bus topics)."""
    display_name: Mapped[str | None] = mapped_column(default=None)
    """Human-readable label shown in the UI; falls back to `name` when unset."""
    role: Mapped[str] = mapped_column(default="")
    """One line shown to the other agents and in the UI."""
    system_prompt: Mapped[str] = mapped_column(default="")
    base_url: Mapped[str] = mapped_column(default="")
    """Model server (OpenAI-compatible base URL) for this agent; empty uses the default."""
    provider: Mapped[str] = mapped_column(default="")
    """'' (the AI Mode default) | 'ollama' | 'openrouter'."""
    credential_id: Mapped[int | None] = mapped_column(default=None)
    """OpenRouter API key for this agent; empty uses the default's. Never copied into a run snapshot."""
    model_override: Mapped[str] = mapped_column(default="")
    temperature: Mapped[float] = mapped_column(default=0.2)
    max_iterations: Mapped[int] = mapped_column(default=15)
    llm_timeout_seconds: Mapped[float] = mapped_column(default=0.0)
    """Seconds one model call may take for this agent; 0 uses AiModeSettings.llm_call_timeout_seconds."""
    max_run_minutes: Mapped[float] = mapped_column(default=0.0)
    """This agent's own time budget within a run, measured from the run's start, same as 0 uses
    AiModeSettings.max_run_minutes. Lets a slow agent (e.g. sinverguenza) get a longer budget than the
    rest of the team without raising the run-wide default - see docs/decisions.md."""
    enabled_tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    mcp_url_override: Mapped[str | None] = mapped_column(default=None)
    """Replaces every enabled_tools MCP custom tool's own mcp_url for this agent's calls only - lets an
    agent whose tools all point at one external MCP server (e.g. tajonaso/HexStrike) be repointed at a new
    host in one place instead of editing each AiCustomTool row."""
    mcp_timeout_seconds: Mapped[float] = mapped_column(default=0.0)
    """How long this agent waits for one MCP custom tool call before giving up; 0 uses
    custom_tools.MCP_TIMEOUT_SECONDS (30s). A built-in tool enforces its own short timeout, but an MCP
    tool can be anything a remote server chooses to run (e.g. a full-range nmap scan or an exploit
    attempt via HexStrike) - 30s is too short for some of those and cuts them off mid-call, which
    looks like a dead server (ReadTimeout) and wastes an iteration rather than reporting a real
    result. Per-agent because that depends on what its MCP tools actually do, not on the agent kind."""
    subscribes: Mapped[list[str]] = mapped_column(JSON, default=list)
    """Topic patterns this agent receives (* = one segment, # = the rest)."""
    publishes: Mapped[list[str]] = mapped_column(JSON, default=list)
    """Topic patterns this agent may publish to."""
    require_approval: Mapped[str] = mapped_column(default="none")
    """none | messages | tools | both: which actions wait for a human."""
    enabled: Mapped[bool] = mapped_column(default=True)
    allow_changes: Mapped[bool] = mapped_column(default=False)
    """May hold tools that change a host (inspect_tools.MUTATING_TOOLS); each such call waits for a human."""
    credential_scope: Mapped[str] = mapped_column(default="bound")
    """Which stored credentials the host-inspection tools may try: 'bound' (only integrations bound to
    the target host - the original behavior), 'pool' (also the credential pool) or 'selected' (also, but
    only the credentials in credential_scope_ids). A host-bound integration always comes first."""
    credential_scope_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    workflow_x: Mapped[float | None] = mapped_column(default=None)
    workflow_y: Mapped[float | None] = mapped_column(default=None)
    """Position of this agent's node on the Workflow canvas; None until the user places it."""
    memory_max_entries_override: Mapped[int] = mapped_column(default=0)
    """0 uses AiModeSettings.memory_max_entries_per_agent; otherwise this agent's own cap on
    `remember` notes kept (oldest pruned first) - e.g. a higher budget for an agent that
    investigates many hosts."""
    memory_max_content_chars_override: Mapped[int] = mapped_column(default=0)
    """0 uses AiModeSettings.memory_max_content_chars; otherwise this agent's own per-note
    truncation length."""
    memory_max_inject_chars_override: Mapped[int] = mapped_column(default=0)
    """0 uses AiModeSettings.memory_max_inject_chars; otherwise this agent's own total injected
    memory budget."""
    fallback_provider: Mapped[str] = mapped_column(default="")
    """'' = no fallback configured | 'ollama' | 'openrouter'. If the primary model call fails, the
    same call is retried once against this endpoint instead of failing the agent outright. Opt-in,
    per-agent only - there is no run-wide default fallback."""
    fallback_base_url: Mapped[str] = mapped_column(default="")
    fallback_model: Mapped[str] = mapped_column(default="")
    fallback_credential_id: Mapped[int | None] = mapped_column(default=None)


class AiAgentMemory(Base, TimestampMixin):
    """One note an agent saved about itself (the `remember` tool) for its own future runs.

    Keyed by the agent's `name`, not `AiAgent.id`: the same durable-identifier idiom
    `settings_snapshot` already uses, so memory reattaches if an agent is deleted and
    recreated under the same name. Capped per agent at write time (see
    AiModeSettings.memory_max_entries_per_agent / AiAgent.memory_max_entries_override,
    resolved by effective_memory_limits in llm/agent_tools.py) so the context injected
    into every future call stays bounded - see docs/decisions.md."""

    __tablename__ = "ai_agent_memory"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_name: Mapped[str] = mapped_column(index=True)
    content: Mapped[str] = mapped_column(Text)


class AiMessage(Base):
    """One message on the bus. The log is the source of truth: a message is
    written here before anyone is handed it."""

    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("ai_runs.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    topic: Mapped[str]
    sender: Mapped[str]
    payload: Mapped[Any] = mapped_column(JSON, default=dict)
    correlation_id: Mapped[str]
    """Shared by every message in one conversation; copied from the message being answered."""
    reply_to: Mapped[str | None]
    hops: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(default="delivered")
    """delivered | held (waiting for a human) | rejected"""
    note: Mapped[str | None]

    deliveries: Mapped[list["AiMessageDelivery"]] = relationship(
        cascade="all, delete-orphan", order_by="AiMessageDelivery.id"
    )


class AiMessageDelivery(Base):
    __tablename__ = "ai_message_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("ai_messages.id", ondelete="CASCADE"), index=True)
    recipient: Mapped[str]
    state: Mapped[str] = mapped_column(default="pending")
    """pending (held) | delivered (in the subscriber's queue) | acked (handled) | rejected"""
    updated_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Report(Base):
    """A saved network and services report. `content` is Markdown; the PDF is rendered from it on
    request. `source` is 'snapshot' (built from the database, no model involved), 'agent:<name>' or
    'telegram'."""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    source: Mapped[str] = mapped_column(default="snapshot")
    content: Mapped[str] = mapped_column(Text, default="")
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    """The build_snapshot() result current when this report was saved, from whichever path saved it -
    manual, Telegram or an agent. Lets a later report's get_status_delta tool show what changed since
    this one, regardless of which report was last."""
    run_id: Mapped[int | None] = mapped_column(default=None, index=True)
    """The AI Mode run that produced this report, for the per-network reports assembled when a run ends."""
    scope: Mapped[str | None] = mapped_column(default=None)
    """What the report covers: a network name, 'All networks' or 'Unassigned'. None for a whole-install
    report (snapshot, Telegram, or the reporter's direct task)."""
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)


FINDING_KINDS = ("os", "patch", "vulnerability", "performance", "incident", "other")
FINDING_SEVERITIES = ("info", "low", "medium", "high", "critical")


class HostFinding(Base):
    """One thing an agent learned about a host that a report should carry: its OS, patch level, a
    vulnerability, a performance problem or a security incident. Structured so a run's reports are built
    from the database rather than from whatever an agent last said in prose. `ip` is the key (a host
    need not be a known Device); `device_id` is filled when it is."""

    __tablename__ = "host_findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(default=None, index=True)
    device_id: Mapped[int | None] = mapped_column(default=None)
    ip: Mapped[str] = mapped_column(index=True)
    kind: Mapped[str]
    severity: Mapped[str] = mapped_column(default="info")
    title: Mapped[str]
    detail: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(default="")
    """The agent that recorded it."""
    observed_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)


class TelegramConfig(Base, TimestampMixin):
    """Singleton settings row for the Telegram bot. The bot token lives in credentials.db;
    credential_id is an opaque reference to it."""

    __tablename__ = "telegram_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=False)
    credential_id: Mapped[int | None] = mapped_column(default=None)
    chat_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    """Only these chats are answered; anyone else is told their chat id and nothing more."""
    notify_alerts: Mapped[bool] = mapped_column(default=True)
    notify_ai_reports: Mapped[bool] = mapped_column(default=True)
    """Whether a report saved by any AI Mode agent (reporter's save_report tool, whether from an
    explicit /report ai, a scheduled run, or an automatic escalation chain like reviewer ->
    bellaco/sinverguenza -> reporter) is pushed to the allowed chats as a PDF. Off still lets a human
    read it from the Reports page; it is not a way to silence that report, only its Telegram push."""
    notify_cost_budget: Mapped[bool] = mapped_column(default=True)
    """Whether crossing AiModeSettings.cost_budget_usd pushes a one-time text notification here."""
    last_update_id: Mapped[int] = mapped_column(default=0)


class AdminUser(Base, TimestampMixin):
    """The single dashboard account. `must_change_password` is true until the default password has been
    replaced; only the password-change, logout and whoami endpoints work in that state."""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True)
    password_hash: Mapped[str]
    must_change_password: Mapped[bool] = mapped_column(default=True)


class AuthSession(Base):
    """A dashboard login. Only the SHA-256 of the cookie token is stored, so a copy of the database
    cannot be used to impersonate anyone."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    expires_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime())


class LoginAttempt(Base):
    """Consecutive failed logins per client address, so the lockout survives a restart."""

    __tablename__ = "login_attempts"

    client: Mapped[str] = mapped_column(primary_key=True)
    failures: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime.datetime | None] = mapped_column(UTCDateTime(), default=None)


class SshHostKey(Base):
    """An SSH host key seen by auto-login. Passwords and keys are only tried against a host whose key a
    human approved (when the setting is on); `public_key` is the key line that was shown for approval."""

    __tablename__ = "ssh_host_keys"
    __table_args__ = (UniqueConstraint("host", "port"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    host: Mapped[str]
    port: Mapped[int] = mapped_column(default=22)
    public_key: Mapped[str]
    fingerprint: Mapped[str]
    approved: Mapped[bool] = mapped_column(default=False)
    changed: Mapped[bool] = mapped_column(default=False)
    """True when the host presented a different key than the one approved earlier."""
    first_seen_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AuditEntry(Base):
    """One successful change made through the API (POST, PUT, PATCH, DELETE). Request bodies are never
    stored, so a secret typed into a form cannot end up here."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    actor: Mapped[str]
    method: Mapped[str]
    path: Mapped[str]
    status: Mapped[int]
