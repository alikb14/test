from __future__ import annotations

from typing import TypeAlias
import logging

from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from app.database import CardType, User
from app.services import ServiceRegistry

Event: TypeAlias = Message | CallbackQuery
logger = logging.getLogger(__name__)


def get_services(event: Event) -> ServiceRegistry:
    bot = event.bot if isinstance(event, Message) else event.message.bot
    services = getattr(bot, "services", None)
    if services is None:
        raise RuntimeError("Service registry is not configured.")
    return services


async def get_current_user(event: Event) -> User | None:
    from_user = event.from_user if isinstance(event, Message) else event.from_user
    if from_user is None:
        return None
    services = get_services(event)
    return await services.users.get_by_telegram_id(from_user.id)


def card_type_title(card_type: CardType) -> str:
    return "آسیا" if card_type is CardType.ASIA else "اثیر"


async def notify_inventory_threshold(
    bot,
    services: ServiceRegistry,
    card_type: CardType,
    amount: int,
    *,
    exclude_user_id: int | None = None,
) -> None:
    remaining = await services.cards.count_available(card_type, amount)
    if remaining > 2:
        return

    title = card_type_title(card_type)
    admins = await services.users.list_admins()
    for admin in admins:
        if not admin.telegram_id:
            continue
        if exclude_user_id is not None and admin.id == exclude_user_id:
            continue
        try:
            await bot.send_message(
                admin.telegram_id,
                f"هشدار موجودی: از کارت {title} مبلغ {amount:,} دینار فقط {remaining} عدد باقی مانده است.",
            )
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            logger.warning(
                "Failed to deliver inventory warning",
                extra={"admin_id": admin.id, "reason": str(exc)},
            )
            continue
