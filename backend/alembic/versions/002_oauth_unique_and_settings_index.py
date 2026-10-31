"""Unique OAuth connection per organization/provider; align user_ai_settings index

Revision ID: 002
Revises: 001
Create Date: 2026-10-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The model declares user_id as unique=True + index=True, which maps to a single unique index.
    op.drop_constraint('user_ai_settings_user_id_key', 'user_ai_settings', type_='unique')
    op.drop_index(op.f('ix_user_ai_settings_user_id'), table_name='user_ai_settings')
    op.create_index(op.f('ix_user_ai_settings_user_id'), 'user_ai_settings', ['user_id'], unique=True)

    op.create_unique_constraint(
        'uq_oauth_connection_organization_provider',
        'oauth_connections',
        ['organization_id', 'provider'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_oauth_connection_organization_provider', 'oauth_connections', type_='unique')

    op.drop_index(op.f('ix_user_ai_settings_user_id'), table_name='user_ai_settings')
    op.create_index(op.f('ix_user_ai_settings_user_id'), 'user_ai_settings', ['user_id'])
    op.create_unique_constraint('user_ai_settings_user_id_key', 'user_ai_settings', ['user_id'])
