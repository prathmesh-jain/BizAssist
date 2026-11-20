"""long-term memory

Revision ID: 008
Revises: 007
Create Date: 2026-11-20 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '008'
down_revision: Union[str, Sequence[str], None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'memories',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('organization_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('created_by_user_id', sa.String(), nullable=True),
        sa.Column('scope', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('topic', sa.String(), nullable=True),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('source_chat_id', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('supersedes_id', sa.String(), nullable=True),
        sa.Column('pinned', sa.Boolean(), nullable=False),
        sa.Column('use_count', sa.Integer(), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'search_vector',
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', coalesce(content, '') || ' ' || coalesce(topic, ''))", persisted=True),
            nullable=True,
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['source_chat_id'], ['chats.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['supersedes_id'], ['memories.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_memories_org_scope_status', 'memories', ['organization_id', 'scope', 'status'])
    op.create_index('ix_memories_org_user', 'memories', ['organization_id', 'user_id'])
    op.create_index('ix_memories_org_kind_created', 'memories', ['organization_id', 'kind', 'created_at'])
    op.create_index('ix_memories_search', 'memories', ['search_vector'], postgresql_using='gin')
    op.add_column(
        'user_ai_settings',
        sa.Column('memory_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('user_ai_settings', 'memory_enabled')
    op.drop_index('ix_memories_search', table_name='memories')
    op.drop_index('ix_memories_org_kind_created', table_name='memories')
    op.drop_index('ix_memories_org_user', table_name='memories')
    op.drop_index('ix_memories_org_scope_status', table_name='memories')
    op.drop_table('memories')
