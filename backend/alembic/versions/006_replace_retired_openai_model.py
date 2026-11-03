"""Replace the retired gpt-4.1-nano model in stored AI settings

OpenAI now rejects gpt-4.1-nano ("model has been deprecated"), so every chat for a
user with it stored would fail. Move those settings to gpt-4.1-mini.

Revision ID: 006
Revises: 005
Create Date: 2026-11-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RETIRED = 'gpt-4.1-nano'
REPLACEMENT = 'gpt-4.1-mini'


def upgrade() -> None:
    for column in ('primary_model', 'fast_model', 'nano_model'):
        op.execute(f"UPDATE user_ai_settings SET {column} = '{REPLACEMENT}' WHERE {column} = '{RETIRED}'")


def downgrade() -> None:
    # Data change only; the retired model can't be restored meaningfully.
    pass
