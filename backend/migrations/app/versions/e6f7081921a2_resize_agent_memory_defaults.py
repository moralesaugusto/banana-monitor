"""resize agent memory defaults to something more realistic

A `remember` note is meant to be one short fact, not a paragraph, and the original per-note
default (500 chars, ~125 tokens) was oversized for that. The injection budget (2000 chars, ~500
tokens) is raised to 3000 (~750 tokens) so roughly the same number of notes (~15) still fit at
the new, smaller per-note size - see docs/ai-cost-and-models.md's "Agent memory" section.

Revision ID: e6f7081921a2
Revises: d5e6f7081920
Create Date: 2026-11-06

"""

from alembic import op

revision = "e6f7081921a2"
down_revision = "d5e6f7081920"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_mode_settings") as batch:
        batch.alter_column("memory_max_content_chars", server_default="200")
        batch.alter_column("memory_max_inject_chars", server_default="3000")
    # Only rows still at the old default are moved - an administrator's own customization (an
    # unlikely but possible exact match on the old number) is left alone.
    op.execute("UPDATE ai_mode_settings SET memory_max_content_chars = 200 WHERE memory_max_content_chars = 500")
    op.execute("UPDATE ai_mode_settings SET memory_max_inject_chars = 3000 WHERE memory_max_inject_chars = 2000")


def downgrade() -> None:
    with op.batch_alter_table("ai_mode_settings") as batch:
        batch.alter_column("memory_max_content_chars", server_default="500")
        batch.alter_column("memory_max_inject_chars", server_default="2000")
    op.execute("UPDATE ai_mode_settings SET memory_max_content_chars = 500 WHERE memory_max_content_chars = 200")
    op.execute("UPDATE ai_mode_settings SET memory_max_inject_chars = 2000 WHERE memory_max_inject_chars = 3000")
