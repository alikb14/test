from __future__ import annotations

import enum
from datetime import datetime, date, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class UserRole(enum.Enum):
    ADMIN = "admin"
    RESPONSIBLE = "responsible"
    USER = "user"


class Department(enum.Enum):
    NETWORK = "network"
    INSTITUTE = "institute"


class CardType(enum.Enum):
    ASIA = "asia"
    ATHIR = "athir"


class CardStatus(enum.Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    SENT = "sent"
    ARCHIVED = "archived"


class InventoryAction(enum.Enum):
    ADD = "add"
    RESERVE = "reserve"
    SEND = "send"
    RESTORE = "restore"
    THRESHOLD_ALERT = "threshold_alert"


class RequestStatus(enum.Enum):
    PENDING_MANAGER = "pending_manager"
    PENDING_ACCOUNTING = "pending_accounting"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class RequestType(enum.Enum):
    FIXED = "fixed"
    CUSTOM = "custom"


class User(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    telegram_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False)
    department: Mapped[Department | None] = mapped_column(Enum(Department))
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    line_expiry: Mapped[date | None] = mapped_column(Date)
    line_type: Mapped[CardType | None] = mapped_column(Enum(CardType))
    can_approve_directly: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    manager: Mapped["User | None"] = relationship(
        "User",
        remote_side="User.id",
        back_populates="members",
    )
    members: Mapped[list["User"]] = relationship(
        "User",
        back_populates="manager",
        cascade="all",
    )
    requests: Mapped[list["RechargeRequest"]] = relationship(
        back_populates="requester",
        cascade="all,delete-orphan",
        foreign_keys="[RechargeRequest.requester_id]",
    )
    responsible_requests: Mapped[list["RechargeRequest"]] = relationship(
        back_populates="responsible",
        foreign_keys="[RechargeRequest.responsible_id]",
    )

    __table_args__ = (
        UniqueConstraint("phone", name="uq_user_phone"),
        UniqueConstraint("telegram_id", name="uq_user_telegram_id"),
    )


class Card(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_type: Mapped[CardType] = mapped_column(Enum(CardType), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[CardStatus] = mapped_column(
        Enum(CardStatus), default=CardStatus.AVAILABLE, nullable=False
    )
    image_file_id: Mapped[str | None] = mapped_column(String(256))
    image_path: Mapped[str | None] = mapped_column(String(255))
    serial_number: Mapped[str | None] = mapped_column(String(128))
    added_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    added_by: Mapped[User | None] = relationship()
    logs: Mapped[list["CardInventoryLog"]] = relationship(
        back_populates="card", cascade="all,delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_card_amount_positive"),
        UniqueConstraint("serial_number", name="uq_card_serial"),
    )


class CardInventoryLog(Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("card.id"), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    action: Mapped[InventoryAction] = mapped_column(Enum(InventoryAction), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    card: Mapped[Card] = relationship(back_populates="logs")
    actor: Mapped[User | None] = relationship()


class RechargeRequest(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    responsible_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    accounting_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    request_type: Mapped[RequestType] = mapped_column(Enum(RequestType), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RequestStatus] = mapped_column(
        Enum(RequestStatus), default=RequestStatus.PENDING_MANAGER
    )
    final_card_id: Mapped[int | None] = mapped_column(ForeignKey("card.id"))
    card_type: Mapped[CardType | None] = mapped_column(Enum(CardType))
    reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    requester: Mapped[User] = relationship(
        back_populates="requests",
        foreign_keys=[requester_id],
    )
    responsible: Mapped[User | None] = relationship(
        back_populates="responsible_requests", foreign_keys=[responsible_id]
    )
    accounting: Mapped[User | None] = relationship(foreign_keys=[accounting_id])
    approver: Mapped[User | None] = relationship(foreign_keys=[approver_id])
    final_card: Mapped[Card | None] = relationship()
    history: Mapped[list["RequestStatusHistory"]] = relationship(
        back_populates="request", cascade="all,delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_recharge_amount_positive"),
    )


class RequestStatusHistory(Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("rechargerequest.id"))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    from_status: Mapped[RequestStatus | None] = mapped_column(Enum(RequestStatus))
    to_status: Mapped[RequestStatus] = mapped_column(Enum(RequestStatus), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    request: Mapped[RechargeRequest] = relationship(back_populates="history")
    actor: Mapped[User | None] = relationship()


class MonthlyReport(Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    total_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    report_path: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint(
            "period_start", "period_end", name="uq_monthly_report_period"
        ),
    )
