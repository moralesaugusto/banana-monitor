"""Pre-flight checks for an agent's settings, run from the Agents edit screen before a run is started.

Nothing here calls a model or reads a credential: it looks at the saved configuration, counts integrations
and, to confirm the model exists, asks the configured Ollama host which models it serves."""

import time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.ai_mode import AgentBase, VerifyCheck, VerifyResult
from app.db.session import get_databases
from app.domain.bootstrap import ensure_default_ai_mode_settings, ensure_default_discovery_settings
from app.domain.enums import AssistantProvider, ServiceType
from app.domain.models import AiAgent, AiCustomTool, Integration, Service
from app.llm.agent_tools import ALL_TOOL_NAMES, WEB_TOOL_NAMES
from app.llm.bus import topic_matches
from app.llm.client import LLMRequestError, call_chat_completions, list_models
from app.llm.inspect_tools import MUTATING_TOOLS
from app.llm.provider import effective_endpoint, load_api_key

LATENCY_WARN_SECONDS = 20.0
LATENCY_TIMEOUT_SECONDS = 45.0

TOOL_NEEDS_INTEGRATION = {
    "ssh_readonly": "generic_ssh",
    "apply_updates": "generic_ssh",
    "winrm_readonly": "windows_winrm",
    "proxmox_get": "proxmox",
    "virustotal_lookup": "virustotal",
}


def unknown_tools(enabled_tools: list[str], custom_names: set[str]) -> list[str]:
    return sorted(set(enabled_tools) - set(ALL_TOOL_NAMES) - custom_names)


def changing_tools_without_permission(enabled_tools: list[str], allow_changes: bool) -> list[str]:
    return [] if allow_changes else sorted(set(enabled_tools) & MUTATING_TOOLS)


class _Checks:
    def __init__(self) -> None:
        self.items: list[VerifyCheck] = []

    def add(self, check_id: str, status: str, title: str, detail: str = "") -> None:
        self.items.append(VerifyCheck(id=check_id, status=status, title=title, detail=detail))  # type: ignore[arg-type]


async def verify_agent(session: AsyncSession, agent: AgentBase, own_id: int | None) -> VerifyResult:
    checks = _Checks()
    others = list(await session.scalars(select(AiAgent).where(AiAgent.id != (own_id or 0))))
    discovery = await ensure_default_discovery_settings(session)

    if any(o.name == agent.name for o in others):
        checks.add("name", "fail", "Name is already used", f"Another agent is called {agent.name}.")
    else:
        checks.add("name", "ok", "Name is available")

    _check_tools(agent, set(await session.scalars(select(AiCustomTool.name))), checks)
    await _check_model(session, agent, checks)

    if agent.system_prompt.strip():
        checks.add("prompt", "ok", "Has its own system prompt")
    else:
        checks.add(
            "prompt", "warn", "No system prompt", "The default discovery prompt is used (it scans ports)."
        )

    _check_messaging(agent, others, checks)
    await _check_prerequisites(session, agent, checks)

    if WEB_TOOL_NAMES & set(agent.enabled_tools):
        if discovery.agent_internet_blocked:
            checks.add(
                "internet",
                "warn",
                "Internet access is blocked by the kill switch",
                "Web tools refuse every call until it is released on the System page.",
            )
        else:
            checks.add(
                "internet", "info", "Reaches the internet", "The red banner shows while it is enabled."
            )

    if not agent.enabled:
        checks.add("state", "info", "Disabled", "It takes no part in runs and cannot be started.")
    elif not discovery.ai_mode_enabled:
        checks.add(
            "state", "info", "AI Mode is switched off", "Enable it in the AI Mode settings to start agents."
        )

    return VerifyResult(ok=not any(c.status == "fail" for c in checks.items), checks=checks.items)


def _check_tools(agent: AgentBase, custom_names: set[str], checks: _Checks) -> None:
    if unknown := unknown_tools(agent.enabled_tools, custom_names):
        checks.add("tools", "fail", "Unknown tools", ", ".join(unknown))
    elif changing := changing_tools_without_permission(agent.enabled_tools, agent.allow_changes):
        checks.add(
            "tools",
            "fail",
            "A tool that changes hosts needs permission",
            f"Tick 'May change hosts' to keep: {', '.join(changing)}.",
        )
    else:
        checks.add("tools", "ok", f"{len(agent.enabled_tools)} tool(s), all known")


def _check_messaging(agent: AgentBase, others: list[AiAgent], checks: _Checks) -> None:
    if not agent.publishes:
        if "publish_message" in agent.enabled_tools:
            checks.add("publishes", "fail", "publish_message is ticked but it may not publish anywhere")
        else:
            checks.add("publishes", "warn", "May not publish anywhere", "Its results reach no other agent.")
    topic = f"result.{agent.name}"
    readers = [o.name for o in others if o.enabled and any(topic_matches(p, topic) for p in o.subscribes)]
    if readers:
        checks.add("receivers", "ok", "Its results have a reader", f"Delivered to: {', '.join(readers)}.")
    else:
        checks.add(
            "receivers", "warn", f"Nobody listens to {topic}", "The answer is only kept in run history."
        )


async def _check_model(session: AsyncSession, agent: AgentBase, checks: _Checks) -> None:
    defaults = await ensure_default_ai_mode_settings(session)
    endpoint = effective_endpoint(
        defaults,
        provider=agent.provider,
        base_url=agent.base_url,
        model=agent.model_override,
        credential_id=agent.credential_id,
    )
    host, model = endpoint.base_url, endpoint.model
    label = "OpenRouter" if endpoint.provider == AssistantProvider.OPENROUTER else "Ollama host"
    try:
        models = await list_models(host)
    except LLMRequestError as exc:
        checks.add("host", "fail", f"{label} is not reachable", f"{host}: {exc}")
        return
    checks.add("host", "ok", f"{label} answers", f"{host} serves {len(models)} model(s).")
    if model in models:
        checks.add("model", "ok", f"Model {model} is available")
        try:
            api_key = await load_api_key(get_databases(), endpoint.credential_id)
        except LLMRequestError as exc:
            checks.add("key", "fail", "API key is missing", str(exc))
            return
        await _check_latency(host, model, api_key, checks)
    else:
        checks.add(
            "model", "fail", f"Model {model} is not on the host", f"Available: {', '.join(models) or 'none'}."
        )


async def _check_latency(host: str, model: str, api_key: str | None, checks: _Checks) -> None:
    """Confirms the model is not just reachable but fast enough to be usable. An unusably slow
    self-hosted model (CPU-only, a contested GPU, too large for the hardware) otherwise only reveals
    itself after a real run times out mid-investigation - this catches it before a run starts."""
    started = time.monotonic()
    try:
        await call_chat_completions(
            base_url=host,
            api_key=api_key,
            model=model,
            messages=[{"role": "user", "content": "Reply with just: ok"}],
            timeout=LATENCY_TIMEOUT_SECONDS,
            max_tokens=8,
        )
    except LLMRequestError as exc:
        detail = f"No reply within {LATENCY_TIMEOUT_SECONDS:.0f}s: {exc}"
        checks.add("latency", "fail", "Model did not respond", detail)
        return
    elapsed = time.monotonic() - started
    if elapsed > LATENCY_WARN_SECONDS:
        checks.add(
            "latency",
            "warn",
            f"Model is slow ({elapsed:.1f}s for a trivial reply)",
            "A real run sends a much larger prompt and will likely exceed the model call timeout. "
            "Consider a smaller/faster model, or raise the timeout under Schedule and time limits.",
        )
    else:
        checks.add("latency", "ok", f"Model replied in {elapsed:.1f}s")


async def _check_prerequisites(session: AsyncSession, agent: AgentBase, checks: _Checks) -> None:
    for tool in agent.enabled_tools:
        needed = TOOL_NEEDS_INTEGRATION.get(tool)
        if needed is None:
            continue
        count = await session.scalar(
            select(func.count())
            .select_from(Integration)
            .where(
                Integration.integration_type == needed,
                Integration.enabled,
                Integration.credential_id.is_not(None),
            )
        )
        if count:
            checks.add(f"needs:{tool}", "ok", f"{tool} has {count} integration(s) to use")
        else:
            detail = f"Add an enabled {needed} integration with a credential."
            checks.add(f"needs:{tool}", "warn", f"{tool} has nothing to inspect", detail)
    if "http_inspect" in agent.enabled_tools:
        web = [ServiceType.HTTP, ServiceType.HTTPS]
        services = await session.scalar(
            select(func.count()).select_from(Service).where(Service.service_type.in_(web))
        )
        if services:
            checks.add("needs:http_inspect", "ok", f"http_inspect has {services} web service(s) to check")
        else:
            checks.add(
                "needs:http_inspect", "warn", "http_inspect has nothing to inspect", "Add an HTTP service."
            )
