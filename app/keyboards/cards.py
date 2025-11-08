from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database import CardType

CARD_AMOUNTS_ASIA = (2000, 5000, 6000, 10000, 15000, 18000, 25000, 35000, 40000, 50000, 100000)
CARD_AMOUNTS_ATHIR = (2000, 5000, 6000, 10000, 15000, 18000, 25000, 30000, 35000, 40000, 50000, 70000, 100000)
CARD_AMOUNTS = (2000, 5000, 6000, 10000, 15000, 18000, 25000, 30000, 35000, 40000, 50000, 70000, 100000)


def card_type_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for card_type in CardType:
        builder.button(
            text="💳 آسیا" if card_type is CardType.ASIA else "💳 اثیر",
            callback_data=f"card_type:{card_type.value}",
        )
    builder.adjust(2)
    return builder.as_markup()


def card_amount_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for amount in CARD_AMOUNTS:
        builder.button(text=f"💰 {amount:,}", callback_data=f"card_amount:{amount}")
    builder.adjust(3, 3, 3, 3, 1)
    return builder.as_markup()


def calculate_tariff(amount: int) -> int:
    """محاسبه تعرفه واقعی کارت بر اساس مبلغ اسمی
    
    تا 15000: مبلغ + 500
    از 18000 به بعد: مبلغ + 1000
    """
    if amount <= 15000:
        return amount + 500
    else:
        return amount + 1000
