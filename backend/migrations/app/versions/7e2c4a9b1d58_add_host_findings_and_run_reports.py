"""add host_findings, run-scoped reports and the run_reports_seeded flag

Revision ID: 7e2c4a9b1d58
Revises: d5e6f7081923
Create Date: 2026-11-18

"""

import sqlalchemy as sa
from alembic import op

revision = "7e2c4a9b1d58"
down_revision = "d5e6f7081923"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "host_findings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("ip", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False, server_default="info"),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(), nullable=False, server_default=""),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_host_findings_run_id", "host_findings", ["run_id"])
    op.create_index("ix_host_findings_ip", "host_findings", ["ip"])
    with op.batch_alter_table("reports") as batch:
        batch.add_column(sa.Column("run_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("scope", sa.String(), nullable=True))
        batch.create_index("ix_reports_run_id", ["run_id"])
    with op.batch_alter_table("ai_mode_settings") as batch:
        batch.add_column(sa.Column("run_reports_seeded", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("ai_mode_settings") as batch:
        batch.drop_column("run_reports_seeded")
    with op.batch_alter_table("reports") as batch:
        batch.drop_index("ix_reports_run_id")
        batch.drop_column("scope")
        batch.drop_column("run_id")
    op.drop_table("host_findings")
