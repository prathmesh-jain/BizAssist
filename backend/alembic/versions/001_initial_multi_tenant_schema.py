"""Initial migration with multi-tenant schema

Revision ID: 001
Revises: 
Create Date: 2026-09-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('full_name', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    # Create user_identities table
    op.create_table(
        'user_identities',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('provider_user_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'provider_user_id', name='uq_provider_provider_user_id')
    )
    op.create_index(op.f('ix_user_identities_user_id'), 'user_identities', ['user_id'])

    # Create organizations table
    op.create_table(
        'organizations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_organizations_slug'), 'organizations', ['slug'], unique=True)

    # Create organization_members table
    op.create_table(
        'organization_members',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('organization_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'user_id', name='uq_organization_user')
    )
    op.create_index(op.f('ix_organization_members_organization_id'), 'organization_members', ['organization_id'])
    op.create_index(op.f('ix_organization_members_user_id'), 'organization_members', ['user_id'])

    # Create user_ai_settings table
    op.create_table(
        'user_ai_settings',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('openai_api_key_encrypted', sa.String(), nullable=True),
        sa.Column('guardrail_enabled', sa.Boolean(), nullable=False),
        sa.Column('primary_model', sa.String(), nullable=False),
        sa.Column('fast_model', sa.String(), nullable=False),
        sa.Column('nano_model', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id')
    )
    op.create_index(op.f('ix_user_ai_settings_user_id'), 'user_ai_settings', ['user_id'])

    # Create chats table
    op.create_table(
        'chats',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('organization_id', sa.String(), nullable=False),
        sa.Column('created_by_user_id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_chats_organization_id'), 'chats', ['organization_id'])
    op.create_index(op.f('ix_chats_created_by_user_id'), 'chats', ['created_by_user_id'])
    op.create_index(op.f('ix_chats_organization_updated'), 'chats', ['organization_id', 'updated_at'])
    op.create_index(op.f('ix_chats_organization_user_updated'), 'chats', ['organization_id', 'created_by_user_id', 'updated_at'])

    # Create messages table
    op.create_table(
        'messages',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('chat_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('content', sa.String(), nullable=False),
        sa.Column('tool_calls', sa.JSON(), nullable=True),
        sa.Column('attachments', sa.JSON(), nullable=True),
        sa.Column('interrupt', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_messages_chat_id'), 'messages', ['chat_id'])
    op.create_index(op.f('ix_messages_user_id'), 'messages', ['user_id'])
    op.create_index(op.f('ix_messages_chat_created'), 'messages', ['chat_id', 'created_at'])

    # Create documents table
    op.create_table(
        'documents',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('organization_id', sa.String(), nullable=False),
        sa.Column('uploaded_by_user_id', sa.String(), nullable=False),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('file_type', sa.String(), nullable=False),
        sa.Column('storage_key', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('chunk_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
        sa.ForeignKeyConstraint(['uploaded_by_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_documents_organization_id'), 'documents', ['organization_id'])
    op.create_index(op.f('ix_documents_uploaded_by_user_id'), 'documents', ['uploaded_by_user_id'])
    op.create_index(op.f('ix_documents_organization_created'), 'documents', ['organization_id', 'created_at'])

    # Create oauth_connections table
    op.create_table(
        'oauth_connections',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('organization_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('provider_account_id', sa.String(), nullable=True),
        sa.Column('access_token_encrypted', sa.String(), nullable=True),
        sa.Column('refresh_token_encrypted', sa.String(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('scopes', sa.JSON(), nullable=True),
        sa.Column('connection_metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_oauth_connections_organization_id'), 'oauth_connections', ['organization_id'])
    op.create_index(op.f('ix_oauth_connections_user_id'), 'oauth_connections', ['user_id'])
    op.create_index(op.f('ix_oauth_connections_organization_provider'), 'oauth_connections', ['organization_id', 'provider'])

    # Create oauth_states table
    op.create_table(
        'oauth_states',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('organization_id', sa.String(), nullable=True),
        sa.Column('state_hash', sa.String(), nullable=False),
        sa.Column('chat_id', sa.String(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
        sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_oauth_states_user_id'), 'oauth_states', ['user_id'])
    op.create_index(op.f('ix_oauth_states_organization_id'), 'oauth_states', ['organization_id'])
    op.create_index(op.f('ix_oauth_states_state_hash'), 'oauth_states', ['state_hash'])
    op.create_index(op.f('ix_oauth_states_expires_at'), 'oauth_states', ['expires_at'])
    op.create_index(op.f('ix_oauth_states_user_state_used_expires'), 'oauth_states', ['user_id', 'state_hash', 'used', 'expires_at'])


def downgrade() -> None:
    op.drop_index(op.f('ix_oauth_states_user_state_used_expires'), table_name='oauth_states')
    op.drop_index(op.f('ix_oauth_states_expires_at'), table_name='oauth_states')
    op.drop_index(op.f('ix_oauth_states_state_hash'), table_name='oauth_states')
    op.drop_index(op.f('ix_oauth_states_organization_id'), table_name='oauth_states')
    op.drop_index(op.f('ix_oauth_states_user_id'), table_name='oauth_states')
    op.drop_table('oauth_states')
    
    op.drop_index(op.f('ix_oauth_connections_organization_provider'), table_name='oauth_connections')
    op.drop_index(op.f('ix_oauth_connections_user_id'), table_name='oauth_connections')
    op.drop_index(op.f('ix_oauth_connections_organization_id'), table_name='oauth_connections')
    op.drop_table('oauth_connections')
    
    op.drop_index(op.f('ix_documents_organization_created'), table_name='documents')
    op.drop_index(op.f('ix_documents_uploaded_by_user_id'), table_name='documents')
    op.drop_index(op.f('ix_documents_organization_id'), table_name='documents')
    op.drop_table('documents')
    
    op.drop_index(op.f('ix_messages_chat_created'), table_name='messages')
    op.drop_index(op.f('ix_messages_user_id'), table_name='messages')
    op.drop_index(op.f('ix_messages_chat_id'), table_name='messages')
    op.drop_table('messages')
    
    op.drop_index(op.f('ix_chats_organization_user_updated'), table_name='chats')
    op.drop_index(op.f('ix_chats_organization_updated'), table_name='chats')
    op.drop_index(op.f('ix_chats_created_by_user_id'), table_name='chats')
    op.drop_index(op.f('ix_chats_organization_id'), table_name='chats')
    op.drop_table('chats')
    
    op.drop_index(op.f('ix_user_ai_settings_user_id'), table_name='user_ai_settings')
    op.drop_table('user_ai_settings')
    
    op.drop_index(op.f('ix_organization_members_user_id'), table_name='organization_members')
    op.drop_index(op.f('ix_organization_members_organization_id'), table_name='organization_members')
    op.drop_table('organization_members')
    
    op.drop_index(op.f('ix_organizations_slug'), table_name='organizations')
    op.drop_table('organizations')
    
    op.drop_index(op.f('ix_user_identities_user_id'), table_name='user_identities')
    op.drop_table('user_identities')
    
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
