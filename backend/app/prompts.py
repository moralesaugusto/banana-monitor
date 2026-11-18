"""Loads agent and chat-assistant system prompts from text files under `agents_system_prompts/`
(a sibling of this module, so it ships inside the `app` package like `domain/hexstrike_tools.json`).

Prompts are plain text, not Python, so a human can read and edit an agent's default behavior
without touching code - including for an agent added later. A file may wrap its text across lines
for readability; wrapped lines are rejoined with a single space so wrapping never changes what the
model actually receives. A blank line starts a new paragraph (kept as a real paragraph break);
anything else is one continuous paragraph, matching how every prompt here reads today.

This only supplies the *default* text new agents (or a reset one) are seeded with - once an
AiAgent/AssistantConfig row exists, its own system_prompt column is what is actually used and is
edited from the UI, never from these files again.
"""

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "agents_system_prompts"


def load_prompt(name: str) -> str:
    """Reads agents_system_prompts/<name>.md and rejoins its wrapped lines into flowing paragraphs."""
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    paragraphs: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            current.append(stripped)
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)
