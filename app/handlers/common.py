from __future__ import annotations

from aiogram import Router, types

router = Router(name="common")


@router.message()
async def fallback(message: types.Message) -> None:
    await message.answer("❓ دستور نامعتبر است. لطفاً از گزینه‌های منو استفاده کنید.")
