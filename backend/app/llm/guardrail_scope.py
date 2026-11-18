"""Which of the administrator's guardrails apply to which tool."""

from collections.abc import Iterable

from app.domain.models import AiGuardrail
from app.llm.inspect_tools import INSPECT_TOOL_NAMES


def guardrails_for(tool: str, guardrails: Iterable[AiGuardrail], *, custom_tool: bool) -> list[AiGuardrail]:
    """Custom tools and host-inspection tools (ssh_readonly and the like) always get every rule. The other
    built-ins only get rules whose scope is "all", so a new rule cannot start blocking a tool that worked."""
    if custom_tool or tool in INSPECT_TOOL_NAMES:
        return list(guardrails)
    return [g for g in guardrails if g.applies_to == "all"]
