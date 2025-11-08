from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import (
    Card,
    CardInventoryLog,
    CardStatus,
    CardType,
    Database,
    InventoryAction,
)
from app.utils.logger import logger


class CardService:
    """Business logic helpers around card inventory management."""

    def __init__(self, database: Database, media_root: Path) -> None:
        self.database = database
        self.media_root = media_root

    async def add_card(
        self,
        *,
        card_type: CardType,
        amount: int,
        actor_id: int | None,
        image_file_id: str | None = None,
        image_path: str | None = None,
        serial_number: str | None = None,
    ) -> Card:
        if image_file_id is None and serial_number is None:
            raise ValueError("Either image_file_id or serial_number must be provided")
        async with self.database.session() as session:
            card = Card(
                card_type=card_type,
                amount=amount,
                image_file_id=image_file_id,
                image_path=image_path,
                serial_number=serial_number,
                added_by_id=actor_id,
            )
            session.add(card)
            await session.flush()
            await self._log(session, card.id, InventoryAction.ADD, actor_id)
            await session.commit()
            await session.refresh(card)
            logger.log_card_operation(
                operation=InventoryAction.ADD.value,
                card_id=card.id,
                user_id=actor_id,
                card_type=card_type.value,
                amount=amount,
            )
            return card

    async def available_summary(self) -> dict[str, dict[int, int]]:
        async with self.database.session() as session:
            result = await session.execute(
                select(Card.card_type, Card.amount, Card.id)
                .where(Card.status == CardStatus.AVAILABLE)
                .order_by(Card.card_type, Card.amount)
            )
            summary: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
            for card_type, amount, _ in result:
                summary[card_type.value][amount] += 1
            return summary

    async def list_available(self, card_type: CardType, amount: int) -> list[Card]:
        async with self.database.session() as session:
            result = await session.execute(
                select(Card)
                .where(
                    Card.card_type == card_type,
                    Card.amount == amount,
                    Card.status == CardStatus.AVAILABLE,
                )
                .order_by(Card.id)
            )
            return list(result.scalars().all())

    async def take_first_available(
        self,
        *,
        card_type: CardType,
        amount: int,
        actor_id: int | None,
    ) -> Card:
        async with self.database.session() as session:
            stmt = (
                select(Card)
                .where(
                    Card.card_type == card_type,
                    Card.amount == amount,
                    Card.status == CardStatus.AVAILABLE,
                )
                .order_by(Card.id)
                .with_for_update(skip_locked=True)
            )
            result = await session.execute(stmt)
            card = result.scalars().first()
            if card is None:
                raise NoResultFound("هیچ کارت فعالی برای این مبلغ و نوع موجود نیست.")
            card.status = CardStatus.RESERVED
            await session.flush()
            await self._log(session, card.id, InventoryAction.RESERVE, actor_id)
            await session.commit()
            await session.refresh(card)
            logger.log_card_operation(
                operation=InventoryAction.RESERVE.value,
                card_id=card.id,
                user_id=actor_id,
                card_type=card.card_type.value,
                amount=card.amount,
            )
            return card

    async def count_available(self, card_type: CardType, amount: int) -> int:
        async with self.database.session() as session:
            result = await session.execute(
                select(func.count())
                .where(
                    Card.card_type == card_type,
                    Card.amount == amount,
                    Card.status == CardStatus.AVAILABLE,
                )
            )
            return result.scalar_one()

    async def reserve_card(self, card_id: int, actor_id: int | None) -> Card:
        async with self.database.session() as session:
            card = await session.get(Card, card_id, with_for_update=True)
            if card is None or card.status is not CardStatus.AVAILABLE:
                raise NoResultFound("Selected card is not available.")
            card.status = CardStatus.RESERVED
            await session.flush()
            await self._log(session, card.id, InventoryAction.RESERVE, actor_id)
            await session.commit()
            await session.refresh(card)
            logger.log_card_operation(
                operation=InventoryAction.RESERVE.value,
                card_id=card.id,
                user_id=actor_id,
                card_type=card.card_type.value,
                amount=card.amount,
            )
            return card

    async def mark_sent(self, card_id: int, actor_id: int | None) -> Card:
        async with self.database.session() as session:
            card = await session.get(Card, card_id, with_for_update=True)
            if card is None:
                raise NoResultFound("Card not found.")
            card.status = CardStatus.SENT
            await session.flush()
            await self._log(session, card.id, InventoryAction.SEND, actor_id)
            await session.commit()
            await session.refresh(card)
            logger.log_card_operation(
                operation=InventoryAction.SEND.value,
                card_id=card.id,
                user_id=actor_id,
                card_type=card.card_type.value,
                amount=card.amount,
            )
            return card

    async def restore_card(self, card_id: int, actor_id: int | None) -> Card:
        async with self.database.session() as session:
            card = await session.get(Card, card_id, with_for_update=True)
            if card is None:
                raise NoResultFound("Card not found.")
            card.status = CardStatus.AVAILABLE
            await session.flush()
            await self._log(session, card.id, InventoryAction.RESTORE, actor_id)
            await session.commit()
            await session.refresh(card)
            logger.log_card_operation(
                operation=InventoryAction.RESTORE.value,
                card_id=card.id,
                user_id=actor_id,
                card_type=card.card_type.value,
                amount=card.amount,
            )
            return card

    async def _log(
        self,
        session: AsyncSession,
        card_id: int,
        action: InventoryAction,
        actor_id: int | None,
        note: str | None = None,
    ) -> None:
        log = CardInventoryLog(
            card_id=card_id,
            action=action,
            actor_id=actor_id,
            note=note,
        )
        session.add(log)
