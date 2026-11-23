"""whatsapp and telegram bots

Revision ID: 009
Revises: 008
Create Date: 2026-11-22 19:50:24.493008

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '009'
down_revision: Union[str, Sequence[str], None] = '008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('jobs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('key', sa.String(), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('run_after', sa.DateTime(timezone=True), nullable=False),
    sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_jobs_status_run_after', 'jobs', ['status', 'run_after'], unique=False)
    op.create_index('ix_jobs_key_status', 'jobs', ['key', 'status'], unique=False)
    op.create_table('bots',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('organization_id', sa.String(), nullable=False),
    sa.Column('created_by_user_id', sa.String(), nullable=True),
    sa.Column('platform', sa.String(), nullable=False),
    sa.Column('audience', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('credentials', sa.Text(), nullable=False),
    sa.Column('webhook_secret', sa.String(), nullable=False),
    sa.Column('external_id', sa.String(), nullable=False),
    sa.Column('handle', sa.String(), nullable=True),
    sa.Column('extra', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('last_inbound_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_reply_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('last_error_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('platform', 'external_id', name='uq_bots_platform_external_id')
    )
    op.create_index(op.f('ix_bots_organization_id'), 'bots', ['organization_id'], unique=False)
    op.create_table('bot_conversations',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('bot_id', sa.String(), nullable=False),
    sa.Column('organization_id', sa.String(), nullable=False),
    sa.Column('external_chat_id', sa.String(), nullable=False),
    sa.Column('contact_name', sa.String(), nullable=True),
    sa.Column('contact_handle', sa.String(), nullable=True),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('chat_id', sa.String(), nullable=True),
    sa.Column('mode', sa.String(), nullable=False),
    sa.Column('pending_interrupt', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('last_inbound_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('bot_id', 'external_chat_id', name='uq_bot_conversations_bot_chat')
    )
    op.create_index('ix_bot_conversations_bot_last', 'bot_conversations', ['bot_id', 'last_message_at'], unique=False)
    op.create_table('bot_identities',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('bot_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('external_user_id', sa.String(), nullable=False),
    sa.Column('display_name', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('bot_id', 'external_user_id', name='uq_bot_identities_bot_external'),
    sa.UniqueConstraint('bot_id', 'user_id', name='uq_bot_identities_bot_user')
    )
    op.create_table('bot_link_codes',
    sa.Column('code', sa.String(), nullable=False),
    sa.Column('bot_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('code')
    )
    op.create_table('bot_messages',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('bot_id', sa.String(), nullable=False),
    sa.Column('conversation_id', sa.String(), nullable=False),
    sa.Column('direction', sa.String(), nullable=False),
    sa.Column('author', sa.String(), nullable=False),
    sa.Column('external_message_id', sa.String(), nullable=True),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('error_code', sa.String(), nullable=True),
    sa.Column('reply_to_id', sa.String(), nullable=True),
    sa.Column('trace', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['conversation_id'], ['bot_conversations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_bot_messages_bot_created', 'bot_messages', ['bot_id', 'created_at'], unique=False)
    op.create_index('ix_bot_messages_conversation_created', 'bot_messages', ['conversation_id', 'created_at'], unique=False)
    op.create_index('uq_bot_messages_external', 'bot_messages', ['bot_id', 'direction', 'external_message_id'], unique=True, postgresql_where='external_message_id IS NOT NULL')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_bot_messages_external', table_name='bot_messages', postgresql_where='external_message_id IS NOT NULL')
    op.drop_index('ix_bot_messages_conversation_created', table_name='bot_messages')
    op.drop_index('ix_bot_messages_bot_created', table_name='bot_messages')
    op.drop_table('bot_messages')
    op.drop_table('bot_link_codes')
    op.drop_table('bot_identities')
    op.drop_index('ix_bot_conversations_bot_last', table_name='bot_conversations')
    op.drop_table('bot_conversations')
    op.drop_index(op.f('ix_bots_organization_id'), table_name='bots')
    op.drop_table('bots')
    op.drop_index('ix_jobs_key_status', table_name='jobs')
    op.drop_index('ix_jobs_status_run_after', table_name='jobs')
    op.drop_table('jobs')
