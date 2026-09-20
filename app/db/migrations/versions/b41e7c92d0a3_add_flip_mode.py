"""add flip mode to bot_config

Revision ID: b41e7c92d0a3
Revises: 6c008000db26
Create Date: 2026-09-20 19:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b41e7c92d0a3'
down_revision: Union[str, None] = '6c008000db26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default so the existing bot_config singleton row gets values when the
    # NOT NULL columns are added; flip mode stays off until explicitly enabled.
    op.add_column('bot_config', sa.Column('flip_mode', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('bot_config', sa.Column('flip_risk_pct', sa.Numeric(), server_default='10', nullable=False))
    op.add_column('bot_config', sa.Column('flip_equity_floor', sa.Numeric(), server_default='25', nullable=False))
    op.add_column('bot_config', sa.Column('flip_equity_target', sa.Numeric(), server_default='100', nullable=False))


def downgrade() -> None:
    op.drop_column('bot_config', 'flip_equity_target')
    op.drop_column('bot_config', 'flip_equity_floor')
    op.drop_column('bot_config', 'flip_risk_pct')
    op.drop_column('bot_config', 'flip_mode')
