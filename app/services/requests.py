from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.database import (
    Card,
    Database,
    MonthlyReport,
    RechargeRequest,
    RequestStatus,
    RequestStatusHistory,
    RequestType,
    User,
)
from app.utils.logger import logger


class RequestService:
    """Encapsulate core recharge request workflow operations."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_request(
        self,
        *,
        requester_id: int,
        responsible_id: int | None,
        amount: int,
        request_type: RequestType,
        status: RequestStatus = RequestStatus.PENDING_MANAGER,
        note: str | None = None,
        card_type: str | None = None,
    ) -> RechargeRequest:
        async with self.database.session() as session:
            request = RechargeRequest(
                requester_id=requester_id,
                responsible_id=responsible_id,
                amount=amount,
                request_type=request_type,
                status=status,
                card_type=card_type,
            )
            session.add(request)
            await session.flush()
            await self._log(
                session,
                request_id=request.id,
                actor_id=requester_id,
                to_status=status,
                note=note,
            )
            await session.commit()
            await session.refresh(request)
            logger.log(
                "Recharge request created",
                request_id=request.id,
                requester_id=requester_id,
                responsible_id=responsible_id,
                amount=amount,
                request_type=request_type.value,
                status=status.value,
            )
            return request

    async def set_status(
        self,
        request_id: int,
        *,
        actor_id: int | None,
        new_status: RequestStatus,
        note: str | None = None,
    ) -> RechargeRequest:
        async with self.database.session() as session:
            request = await session.get(
                RechargeRequest, request_id, with_for_update=True
            )
            if request is None:
                raise NoResultFound("Request not found.")
            previous_status = request.status
            request.status = new_status
            request.updated_at = datetime.now(timezone.utc)
            await session.flush()
            await self._log(
                session,
                request_id=request.id,
                actor_id=actor_id,
                from_status=previous_status,
                to_status=new_status,
                note=note,
            )
            await session.commit()
            await session.refresh(request)
            logger.log(
                "Recharge request status updated",
                request_id=request.id,
                actor_id=actor_id,
                from_status=previous_status.value if previous_status else None,
                to_status=new_status.value,
                note=note,
            )
            return request

    async def get_request(self, request_id: int) -> RechargeRequest | None:
        async with self.database.session() as session:
            return await session.get(RechargeRequest, request_id)

    async def export_consumed_requests(
        self,
        *,
        responsible_id: int | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[dict]:
        async with self.database.session() as session:
            requester_alias = aliased(User)
            responsible_alias = aliased(User)
            approver_alias = aliased(User)
            stmt = (
                select(
                    RechargeRequest.id,
                    RechargeRequest.amount,
                    RechargeRequest.request_type,
                    RechargeRequest.updated_at,
                    requester_alias.full_name.label("requester_name"),
                    responsible_alias.full_name.label("responsible_name"),
                    approver_alias.full_name.label("approver_name"),
                    Card.card_type,
                )
                .join(requester_alias, RechargeRequest.requester_id == requester_alias.id)
                .outerjoin(
                    responsible_alias,
                    RechargeRequest.responsible_id == responsible_alias.id,
                )
                .outerjoin(
                    approver_alias,
                    RechargeRequest.approver_id == approver_alias.id,
                )
                .outerjoin(Card, RechargeRequest.final_card_id == Card.id)
                .where(RechargeRequest.status == RequestStatus.APPROVED)
            )
            if responsible_id is not None:
                stmt = stmt.where(RechargeRequest.responsible_id == responsible_id)
            if start is not None:
                stmt = stmt.where(RechargeRequest.updated_at >= start)
            if end is not None:
                stmt = stmt.where(RechargeRequest.updated_at <= end)

            result = await session.execute(stmt.order_by(RechargeRequest.updated_at))
            rows = result.all()
            data: list[dict] = []
            for row in rows:
                data.append(
                    {
                        "id": row.id,
                        "amount": row.amount,
                        "type": row.request_type.value,
                        "updated_at": row.updated_at,
                        "requester": row.requester_name,
                        "responsible": row.responsible_name,
                        "approver": row.approver_name,
                        "card_type": row.card_type.value if row.card_type else None,
                    }
                )
            return data

    async def attach_card(
        self,
        request_id: int,
        *,
        card_id: int,
        actor_id: int | None,
    ) -> RechargeRequest:
        async with self.database.session() as session:
            request = await session.get(
                RechargeRequest, request_id, with_for_update=True
            )
            if request is None:
                raise NoResultFound("Request not found.")
            request.final_card_id = card_id
            await session.flush()
            await self._log(
                session,
                request_id=request.id,
                actor_id=actor_id,
                from_status=request.status,
                to_status=request.status,
                note="Card assigned",
            )
            await session.commit()
            await session.refresh(request)
            logger.log(
                "Recharge request card attached",
                request_id=request.id,
                card_id=card_id,
                actor_id=actor_id,
            )
            return request

    async def set_approver(
        self,
        request_id: int,
        approver_id: int,
    ) -> RechargeRequest:
        """ثبت کسی که کارت را تایید و ارسال کرده است"""
        async with self.database.session() as session:
            request = await session.get(
                RechargeRequest, request_id, with_for_update=True
            )
            if request is None:
                raise NoResultFound("Request not found.")
            request.approver_id = approver_id
            await session.commit()
            await session.refresh(request)
            logger.log(
                "Recharge request approver set",
                request_id=request.id,
                approver_id=approver_id,
            )
            return request

    async def record_monthly_report(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
        total_amount: int,
        report_path: str,
    ) -> MonthlyReport:
        async with self.database.session() as session:
            stmt = select(MonthlyReport).where(
                MonthlyReport.period_start == period_start.date(),
                MonthlyReport.period_end == period_end.date(),
            )
            result = await session.execute(stmt)
            report = result.scalars().first()
            if report:
                report.total_amount = total_amount
                report.report_path = report_path
            else:
                report = MonthlyReport(
                    period_start=period_start.date(),
                    period_end=period_end.date(),
                    total_amount=total_amount,
                    report_path=report_path,
                )
                session.add(report)
            await session.commit()
            await session.refresh(report)
            logger.log(
                "Monthly report recorded",
                report_id=report.id,
                period_start=str(period_start.date()),
                period_end=str(period_end.date()),
                total_amount=total_amount,
                report_path=report_path,
            )
            return report

    async def _log(
        self,
        session: AsyncSession,
        *,
        request_id: int,
        actor_id: int | None,
        to_status: RequestStatus,
        from_status: RequestStatus | None = None,
        note: str | None = None,
    ) -> None:
        history = RequestStatusHistory(
            request_id=request_id,
            actor_id=actor_id,
            from_status=from_status,
            to_status=to_status,
            note=note,
        )
        session.add(history)
