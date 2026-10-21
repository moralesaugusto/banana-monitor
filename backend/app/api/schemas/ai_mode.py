import datetime
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import AssistantProvider
from app.llm.bus import valid_pattern
from app.llm.command_policy import validate_command


class AiModeSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool = False
    system_prompt: str
    model_override: str
    llm_base_url: str
    llm_model: str
    llm_provider: AssistantProvider = AssistantProvider.OLLAMA
    llm_credential_id: int | None = None
    llm_call_timeout_seconds: float
    max_iterations: int
    temperature: float
    max_targets: int
    enabled_tools: list[str]
    allow_undefined_network_scan: bool = False
    undefined_scan_max_hosts: int
    ollama_max_concurrent_calls: int
    openrouter_max_concurrent_calls: int


class AiModeSettingsUpdate(BaseModel):
    enabled: bool | None = None
    system_prompt: str | None = Field(default=None, max_length=8000)
    model_override: str | None = Field(default=None, max_length=200)
    llm_base_url: str | None = Field(default=None, pattern=r"^https?://\S+$", max_length=300)
    llm_model: str | None = Field(default=None, min_length=1, max_length=200)
    llm_provider: AssistantProvider | None = None
    llm_credential_id: int | None = None
    llm_call_timeout_seconds: float | None = Field(default=None, ge=10, le=1800)
    max_iterations: int | None = Field(default=None, ge=1, le=40)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_targets: int | None = Field(default=None, ge=1, le=100)
    enabled_tools: list[str] | None = None
    allow_undefined_network_scan: bool | None = None
    undefined_scan_max_hosts: int | None = Field(default=None, ge=1, le=1024)
    ollama_max_concurrent_calls: int | None = Field(default=None, ge=1, le=16)
    openrouter_max_concurrent_calls: int | None = Field(default=None, ge=1, le=16)


class ToolInfo(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]
    enabled: bool


class AiModeTools(BaseModel):
    default_system_prompt: str
    tools: list[ToolInfo]
    guardrails: list[str]
    allowed_nmap_flags: str


class AiRunStart(BaseModel):
    targets: list[str] = []
    """Empty means: every known non-self device IP (capped by max_targets)."""
    dry_run: bool = False
    entry_agent: str = "discoverer"
    message: str | None = Field(default=None, max_length=4000)
    """Task text for the entry agent; empty means 'discover services on the targets'."""


class AgentStartRequest(BaseModel):
    targets: list[str] = []
    """Hosts to hand this agent, even ones never discovered - validated against the configured
    network/loopback only when a tool actually runs against one, same as a multi-agent run."""
    message: str | None = Field(default=None, max_length=4000)
    """Task text for this agent; empty keeps the usual default task."""


class AiRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    paused: bool = False
    started_by: str = "manual"
    stop_reason: str | None = None
    entry_agent: str = ""

    id: int
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    status: str
    targets: list[str]
    dry_run: bool
    model: str
    prompt_tokens: int
    completion_tokens: int
    summary: str | None
    error: str | None
    step_count: int = 0
    services_recorded: int = 0


class AiRunStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    idx: int
    ts: datetime.datetime
    kind: str
    name: str | None
    agent: str | None = None
    request: Any
    response: Any
    duration_ms: int
    prompt_tokens: int
    completion_tokens: int


class AiRunDetail(AiRunSummary):
    base_url: str
    system_prompt: str
    settings_snapshot: dict[str, Any]
    steps: list[AiRunStepRead]


class CustomToolBase(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,39}$")
    description: str = Field(min_length=1, max_length=1000)
    kind: Literal["command", "mcp"]
    command: list[str] = []
    """argv template for kind=command; first item is the executable, {target} and {port} are substituted."""
    mcp_url: str | None = Field(default=None, pattern=r"^https?://")
    mcp_tool: str | None = None
    parameters: dict[str, Any] = {}
    """JSON schema shown to the model (kind=mcp; command tools always take target and port)."""
    enabled: bool = True

    @model_validator(mode="after")
    def _kind_fields(self) -> "CustomToolBase":
        if self.kind == "command":
            validate_command(self.command)
        if self.kind == "mcp" and not (self.mcp_url and self.mcp_tool):
            raise ValueError("mcp tools need mcp_url and mcp_tool")
        return self


class CustomToolRead(CustomToolBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


class GuardrailBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    kind: Literal["deny_regex", "allow_regex"]
    pattern: str = Field(min_length=1, max_length=500)
    enabled: bool = True

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid regular expression: {exc}") from exc
        return value


class GuardrailRead(GuardrailBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


class AgentBase(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,29}$")
    display_name: str | None = Field(default=None, max_length=100)
    role: str = Field(default="", max_length=200)
    system_prompt: str = Field(default="", max_length=8000)
    base_url: str = Field(default="", max_length=300, pattern=r"^(https?://\S+)?$")
    provider: Literal["", "ollama", "openrouter"] = ""
    """Empty uses the AI Mode default provider."""
    credential_id: int | None = None
    model_override: str = Field(default="", max_length=200)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_iterations: int = Field(default=15, ge=1, le=60)
    llm_timeout_seconds: float = Field(default=0, ge=0, le=1800)
    """0 uses the default model call timeout."""
    max_run_minutes: float = Field(default=0, ge=0, le=240)
    """0 uses the default run time limit (AiModeSettings.max_run_minutes)."""
    enabled_tools: list[str] = []
    mcp_url_override: str | None = Field(default=None, max_length=300, pattern=r"^(https?://\S+)?$")
    """Replaces every MCP custom tool's own mcp_url for this agent's calls only."""
    mcp_timeout_seconds: float = Field(default=0, ge=0, le=600)
    """0 uses custom_tools.MCP_TIMEOUT_SECONDS (30s)."""
    subscribes: list[str] = []
    publishes: list[str] = []
    require_approval: Literal["none", "messages", "tools", "both"] = "none"
    enabled: bool = True
    allow_changes: bool = False
    workflow_x: float | None = None
    workflow_y: float | None = None

    @field_validator("subscribes", "publishes")
    @classmethod
    def _valid_patterns(cls, patterns: list[str]) -> list[str]:
        for pattern in patterns:
            if not valid_pattern(pattern):
                raise ValueError(f"invalid topic pattern {pattern!r}: dot-separated words, * or a final #")
        return patterns


class WorkflowUpdate(BaseModel):
    enabled: bool | None = None
    workflow_x: float | None = None
    workflow_y: float | None = None


class AgentRead(AgentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


class VerifyCheck(BaseModel):
    id: str
    status: Literal["ok", "info", "warn", "fail"]
    title: str
    detail: str = ""


class VerifyResult(BaseModel):
    ok: bool
    """True when no check failed; warnings and notes do not make it false."""
    checks: list[VerifyCheck]


class DeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recipient: str
    state: str


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    ts: datetime.datetime
    topic: str
    sender: str
    payload: Any
    correlation_id: str
    reply_to: str | None
    hops: int
    status: str
    note: str | None
    deliveries: list[DeliveryRead] = []


class HumanMessage(BaseModel):
    run_id: int
    topic: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=4000)
    correlation_id: str | None = None


class Decision(BaseModel):
    payload: dict[str, Any] | None = None
    """Edited payload (for tool approvals: {"tool": ..., "arguments": {...}})."""
    reason: str = Field(default="", max_length=500)


class ScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    schedule_enabled: bool
    schedule_interval_seconds: int
    schedule_entry_agent: str
    max_run_minutes: int
    max_targets: int
    llm_call_timeout_seconds: float
    last_scheduled_at: datetime.datetime | None
    next_run_at: datetime.datetime | None = None


class ScheduleUpdate(BaseModel):
    schedule_enabled: bool | None = None
    schedule_interval_seconds: int | None = Field(default=None, ge=30, le=604800)
    schedule_entry_agent: str | None = None
    max_run_minutes: int | None = Field(default=None, ge=1, le=240)
    max_targets: int | None = Field(default=None, ge=1, le=100)
    llm_call_timeout_seconds: float | None = Field(default=None, ge=10, le=1800)


class AgentState(BaseModel):
    name: str
    display_name: str | None = None
    enabled: bool
    state: Literal["working", "waiting", "paused", "scheduled", "stopped", "disabled"]
    """working: handling a message now. waiting: run active, nothing to do yet. paused: a human paused
    the run. scheduled: no run active but a scheduled run will start it. stopped: no run active and none
    scheduled. disabled: switched off, takes no part in runs."""
    activity: Literal["llm", "tool", "held"] | None = None
    """Only meaningful when state == "working": llm (waiting on the model), tool (running tool call(s)),
    held (a tool call or message is parked for human approval)."""
    queued: int = 0


class RunStatus(BaseModel):
    id: int
    started_by: str
    started_at: datetime.datetime
    deadline_at: datetime.datetime
    paused: bool


class AiStatus(BaseModel):
    ai_enabled: bool
    run: RunStatus | None
    last_run: AiRunSummary | None
    agents: list[AgentState]
    schedule: ScheduleRead


class BusParty(BaseModel):
    agent: str
    enabled: bool
    pattern: str
    """The subscription or publish pattern that matched the topic."""


class BusRoute(BaseModel):
    topic: str
    valid: bool
    subscribers: list[BusParty]
    publishers: list[BusParty]


class BusTopicStats(BaseModel):
    topic: str
    messages: int
    held: int
    last_ts: datetime.datetime
    publishers: list[str]
    recipients: list[str]
    deliveries: dict[str, int]
    """Delivery rows by state (pending, delivered, acked, rejected, dropped)."""


class BusOverview(BaseModel):
    run_id: int | None
    """None means every run."""
    total_messages: int
    topics: list[BusTopicStats]


class BusGauge(BaseModel):
    used: float
    limit: float | None
    """None when the run has no such limit."""


class BusAgentHealth(BaseModel):
    name: str
    queued: int
    working: bool
    held: int
    """Messages this agent published that wait for a human."""
    dropped: int
    """Deliveries to this agent that were discarded because it was stopped."""


class BusHeldMessage(BaseModel):
    message_id: int
    topic: str
    sender: str
    ts: datetime.datetime
    age_seconds: float
    overdue: bool
    """Waiting longer than the approval timeout: it is treated as rejected."""


class BusProblem(BaseModel):
    kind: Literal["dropped", "rejected"]
    message_id: int
    topic: str
    sender: str
    recipient: str | None
    reason: str
    ts: datetime.datetime


class BusHealth(BaseModel):
    run_id: int
    active: bool
    messages: BusGauge
    hops: BusGauge
    seconds: BusGauge
    approval_timeout_seconds: float
    agents: list[BusAgentHealth]
    held: list[BusHeldMessage]
    problems: list[BusProblem]
