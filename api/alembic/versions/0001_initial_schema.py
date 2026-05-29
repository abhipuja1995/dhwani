"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "campaigns",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("type", sa.String, nullable=False, server_default="batch"),
        sa.Column("dial_mode", sa.String, nullable=False, server_default="progressive"),
        sa.Column("status", sa.String, nullable=False, server_default="draft"),
        sa.Column("caller_id", sa.String),
        sa.Column("dial_ratio", sa.Float, server_default="1.5"),
        sa.Column("max_drop_rate", sa.Float, server_default="0.03"),
        sa.Column("retry_attempts", sa.Integer, server_default="3"),
        sa.Column("retry_delay_minutes", sa.Integer, server_default="60"),
        sa.Column("schedule_start", sa.DateTime(timezone=True)),
        sa.Column("schedule_end", sa.DateTime(timezone=True)),
        sa.Column("calling_hours_start", sa.String, server_default="09:00"),
        sa.Column("calling_hours_end", sa.String, server_default="21:00"),
        sa.Column("timezone", sa.String, server_default="Asia/Kolkata"),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "agents",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("username", sa.String, unique=True, nullable=False),
        sa.Column("display_name", sa.String, nullable=False),
        sa.Column("hashed_password", sa.String, nullable=False),
        sa.Column("skills", sa.JSON),
        sa.Column("status", sa.String, server_default="offline"),
        sa.Column("current_call_id", sa.String),
    )

    op.create_table(
        "contacts",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("campaign_id", sa.String, sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("phone", sa.String, nullable=False),
        sa.Column("name", sa.String),
        sa.Column("language", sa.String, server_default="hi"),
        sa.Column("custom_data", sa.JSON),
        sa.Column("status", sa.String, server_default="pending"),
        sa.Column("attempts", sa.Integer, server_default="0"),
        sa.Column("last_dialed_at", sa.DateTime(timezone=True)),
        sa.Column("is_dnd", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_contacts_campaign_id", "contacts", ["campaign_id"])
    op.create_index("ix_contacts_status", "contacts", ["status"])

    op.create_table(
        "calls",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("campaign_id", sa.String, sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("contact_id", sa.String, sa.ForeignKey("contacts.id"), nullable=False),
        sa.Column("agent_id", sa.String, sa.ForeignKey("agents.id")),
        sa.Column("fs_uuid", sa.String),
        sa.Column("status", sa.String, server_default="initiated"),
        sa.Column("amd_result", sa.String),
        sa.Column("duration_seconds", sa.Integer),
        sa.Column("recording_path", sa.String),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("bridged_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_calls_campaign_id", "calls", ["campaign_id"])
    op.create_index("ix_calls_fs_uuid", "calls", ["fs_uuid"])
    op.create_index("ix_calls_agent_id", "calls", ["agent_id"])


def downgrade():
    op.drop_table("calls")
    op.drop_table("contacts")
    op.drop_table("agents")
    op.drop_table("campaigns")
