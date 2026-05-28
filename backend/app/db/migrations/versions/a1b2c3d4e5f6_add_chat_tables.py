"""add chat tables

Revision ID: a1b2c3d4e5f6
Revises: 798e2cd5eda2
Create Date: 2026-05-20 21:00:00.000000

Adds the Phase B persistence layer for the worship/music chatbot:
``chat_conversations`` (one row per sidebar conversation) and
``chat_messages`` (one row per turn). In Phase A both tables stay empty;
the chat service uses an in-memory registry + browser localStorage. Run
``alembic upgrade head`` only when activating Phase B.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '798e2cd5eda2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chat_conversations',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=True),
        sa.Column('job_context', sa.JSON(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_chat_conversations_user_id'),
        'chat_conversations',
        ['user_id'],
        unique=False,
    )

    op.create_table(
        'chat_messages',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('conversation_id', sa.String(length=32), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('content_text', sa.Text(), nullable=False),
        sa.Column('content_json', sa.JSON(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['conversation_id'],
            ['chat_conversations.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_chat_messages_conversation_id'),
        'chat_messages',
        ['conversation_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_chat_messages_conversation_id'),
        table_name='chat_messages',
    )
    op.drop_table('chat_messages')
    op.drop_index(
        op.f('ix_chat_conversations_user_id'),
        table_name='chat_conversations',
    )
    op.drop_table('chat_conversations')
