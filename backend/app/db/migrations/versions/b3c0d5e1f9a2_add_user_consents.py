"""add user_consents table

Revision ID: b3c0d5e1f9a2
Revises: a1b2c3d4e5f6
Create Date: 2026-05-28

User consent log for ToS / privacy / age / marketing — see
docs/legal/consent_ui_spec.md for the spec and docs/legal/privacy_policy.md
for the policy this enforces.

One row PER (user_id, consent_type, version). Old rows stay (PIPA audit
trail). Revoking sets ``revoked_at`` instead of deleting.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "b3c0d5e1f9a2"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_consents",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("consent_type", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_user_consents_user_type_version",
        "user_consents",
        ["user_id", "consent_type", "version"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_consents_user_type_version", table_name="user_consents")
    op.drop_table("user_consents")
