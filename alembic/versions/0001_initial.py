"""Initial database schema

Revision ID: 3e0ad35df0c0
Revises:
Create Date: 2025-10-13 13:42:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "3e0ad35df0c0"
down_revision = None
branch_labels = None
depends_on = None


userrole = sa.Enum("ADMIN", "RESPONSIBLE", "USER", name="userrole")
department = sa.Enum("NETWORK", "INSTITUTE", name="department")
cardtype = sa.Enum("ASIA", "ATHIR", name="cardtype")
cardstatus = sa.Enum("AVAILABLE", "RESERVED", "SENT", "ARCHIVED", name="cardstatus")
inventoryaction = sa.Enum(
    "ADD", "RESERVE", "SEND", "RESTORE", "THRESHOLD_ALERT", name="inventoryaction"
)
requesttype = sa.Enum("FIXED", "CUSTOM", name="requesttype")
requeststatus = sa.Enum(
    "PENDING_MANAGER",
    "PENDING_ACCOUNTING",
    "APPROVED",
    "REJECTED",
    "CANCELLED",
    name="requeststatus",
)


def upgrade() -> None:
    bind = op.get_bind()
    userrole.create(bind, checkfirst=True)
    department.create(bind, checkfirst=True)
    cardtype.create(bind, checkfirst=True)
    cardstatus.create(bind, checkfirst=True)
    inventoryaction.create(bind, checkfirst=True)
    requesttype.create(bind, checkfirst=True)
    requeststatus.create(bind, checkfirst=True)

    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("telegram_id", sa.Integer(), nullable=True),
        sa.Column("role", userrole, nullable=False),
        sa.Column("department", department, nullable=True),
        sa.Column("manager_id", sa.Integer(), nullable=True),
        sa.Column("line_expiry", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["manager_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone", name="uq_user_phone"),
        sa.UniqueConstraint("telegram_id", name="uq_user_telegram_id"),
    )

    op.create_table(
        "card",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("card_type", cardtype, nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            cardstatus,
            nullable=False,
            server_default=sa.text("'AVAILABLE'"),
        ),
        sa.Column("image_file_id", sa.String(length=256), nullable=True),
        sa.Column("image_path", sa.String(length=255), nullable=True),
        sa.Column("added_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["added_by_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("amount > 0", name="ck_card_amount_positive"),
    )

    op.create_table(
        "rechargerequest",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("requester_id", sa.Integer(), nullable=False),
        sa.Column("responsible_id", sa.Integer(), nullable=True),
        sa.Column("accounting_id", sa.Integer(), nullable=True),
        sa.Column("request_type", requesttype, nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            requeststatus,
            nullable=False,
            server_default=sa.text("'PENDING_MANAGER'"),
        ),
        sa.Column("final_card_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("amount > 0", name="ck_recharge_amount_positive"),
        sa.ForeignKeyConstraint(["accounting_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["final_card_id"], ["card.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requester_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["responsible_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "cardinventorylog",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("action", inventoryaction, nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["card_id"], ["card.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "monthlyreport",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "total_amount",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("report_path", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "period_start", "period_end", name="uq_monthly_report_period"
        ),
    )

    op.create_table(
        "requeststatushistory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("from_status", requeststatus, nullable=True),
        sa.Column("to_status", requeststatus, nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["request_id"], ["rechargerequest.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("requeststatushistory")
    op.drop_table("monthlyreport")
    op.drop_table("cardinventorylog")
    op.drop_table("rechargerequest")
    op.drop_table("card")
    op.drop_table("user")
    bind = op.get_bind()
    requeststatus.drop(bind, checkfirst=True)
    requesttype.drop(bind, checkfirst=True)
    inventoryaction.drop(bind, checkfirst=True)
    cardstatus.drop(bind, checkfirst=True)
    cardtype.drop(bind, checkfirst=True)
    department.drop(bind, checkfirst=True)
    userrole.drop(bind, checkfirst=True)
