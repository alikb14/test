"""Add card_type to RechargeRequest

Revision ID: 2025_11_04_2000
Revises: 0a120daed45c
Create Date: 2025-11-04 20:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision = '2025_11_04_2000'
down_revision = '0a120daed45c'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Add card_type column to rechargerequest table
    op.add_column('rechargerequest', 
                 sa.Column('card_type', 
                          sa.Enum('ASIA', 'ATHIR', name='cardtype'), 
                          nullable=True))

def downgrade() -> None:
    # Drop card_type column from rechargerequest table
    op.drop_column('rechargerequest', 'card_type')
