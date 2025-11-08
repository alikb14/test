"""add approval fields

Revision ID: 0002
Revises: 3e0ad35df0c0
Create Date: 2025-11-03

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0002'
down_revision = '3e0ad35df0c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add can_approve_directly to user table
    with op.batch_alter_table('user') as batch_op:
        batch_op.add_column(sa.Column('can_approve_directly', sa.Boolean(), nullable=False, server_default=sa.false()))
    
    # Add approver_id to rechargerequest table
    with op.batch_alter_table('rechargerequest') as batch_op:
        batch_op.add_column(sa.Column('approver_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_rechargerequest_approver_id', 'user', ['approver_id'], ['id'])


def downgrade() -> None:
    # Remove approver_id from rechargerequest table
    with op.batch_alter_table('rechargerequest') as batch_op:
        batch_op.drop_constraint('fk_rechargerequest_approver_id', type_='foreignkey')
        batch_op.drop_column('approver_id')
    
    # Remove can_approve_directly from user table
    with op.batch_alter_table('user') as batch_op:
        batch_op.drop_column('can_approve_directly')
