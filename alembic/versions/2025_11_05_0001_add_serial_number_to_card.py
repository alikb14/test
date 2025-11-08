"""Add serial_number to Card table

Revision ID: 2025_11_05_0001
Revises: 2025_11_04_2000
Create Date: 2025-11-05 00:30:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '2025_11_05_0001'
down_revision = '2025_11_04_2000'
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns('card')}
    if 'serial_number' not in existing_columns:
        op.add_column('card', sa.Column('serial_number', sa.String(length=128), nullable=True))

    existing_indexes = {index["name"] for index in inspector.get_indexes('card')}
    if 'ix_card_serial_unique' not in existing_indexes:
        op.create_index('ix_card_serial_unique', 'card', ['serial_number'], unique=True)

def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes('card')}
    if 'ix_card_serial_unique' in existing_indexes:
        op.drop_index('ix_card_serial_unique', table_name='card')

    existing_columns = {column["name"] for column in inspector.get_columns('card')}
    if 'serial_number' in existing_columns:
        op.drop_column('card', 'serial_number')
