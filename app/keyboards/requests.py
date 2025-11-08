from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.keyboards.cards import CARD_AMOUNTS


def charge_amount_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for amount in CARD_AMOUNTS:
        builder.button(text=f"💰 {amount:,}", callback_data=f"charge_amount:{amount}")
    builder.button(text="✏️ حواله مبلغ دلخواه", callback_data="charge_amount:custom")
    builder.adjust(2, 1)
    return builder.as_markup()
