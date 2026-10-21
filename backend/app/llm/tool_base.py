"""Pieces shared by every agent tool module (kept apart so tool modules can import each other's results
without importing `agent_tools`, which registers them)."""

MAX_OUTPUT_CHARS = 4000


class AgentToolError(RuntimeError):
    pass


def truncate(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS] + "\n...[truncated]"
