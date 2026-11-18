"""anchor memory entries default to max_targets; raise inject budget to match

memory_max_entries_per_agent moves from 30 (an arbitrary round number) to 50 - anchored to
2x AiModeSettings.max_targets (default 25, how many devices one scheduled run sweeps), so
memory survives roughly two full scheduled cycles before the oldest notes are pruned.
memory_max_inject_chars moves from 3000 to 4000 (~1000 tokens) in proportion, so the larger
retained history is matched by a proportionally larger share actually reaching the model -
see docs/decisions.md and docs/ai-cost-and-models.md's "Agent memory" section.

Revision ID: f7081922b3c4
Revises: e6f7081921a2
Create Date: 2026-11-06

"""

from alembic import op

revision = "f7081922b3c4"
down_revision = "e6f7081921a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_mode_settings") as batch:
        batch.alter_column("memory_max_entries_per_agent", server_default="50")
        batch.alter_column("memory_max_inject_chars", server_default="4000")
    # Only rows still at the old default are moved - an administrator's own customization (an
    # unlikely but possible exact match on the old number) is left alone.
    op.execute(
        "UPDATE ai_mode_settings SET memory_max_entries_per_agent = 50 WHERE memory_max_entries_per_agent = 30"
    )
    op.execute("UPDATE ai_mode_settings SET memory_max_inject_chars = 4000 WHERE memory_max_inject_chars = 3000")


def downgrade() -> None:
    with op.batch_alter_table("ai_mode_settings") as batch:
        batch.alter_column("memory_max_entries_per_agent", server_default="30")
        batch.alter_column("memory_max_inject_chars", server_default="3000")
    op.execute(
        "UPDATE ai_mode_settings SET memory_max_entries_per_agent = 30 WHERE memory_max_entries_per_agent = 50"
    )
    op.execute("UPDATE ai_mode_settings SET memory_max_inject_chars = 3000 WHERE memory_max_inject_chars = 4000")
