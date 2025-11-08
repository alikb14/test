from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.keyboards.common import cancel_to_main_keyboard, user_main_keyboard
from app.keyboards.requests import charge_amount_keyboard
from app.utils.states import ChargeRequestFlow, UserMenu


router = Router(name="user")
CANCEL_TEXT = "🔙 بازگشت به منوی اصلی"


@router.message(UserMenu.idle, F.text == "🔋 درخواست شارژ")
async def user_request_charge(message: Message, state: FSMContext) -> None:
    await state.set_state(ChargeRequestFlow.choosing_amount)
    await state.update_data(origin="user")
    await message.answer(
        "برای لغو می‌توانید از دکمه «🔙 بازگشت به منوی اصلی» استفاده کنید.",
        reply_markup=cancel_to_main_keyboard(),
    )
    await message.answer(
        "💰 مبلغ شارژ مورد نظر را انتخاب کنید.",
        reply_markup=charge_amount_keyboard(),
    )


@router.message(
    StateFilter(
        ChargeRequestFlow.choosing_amount,
        ChargeRequestFlow.waiting_for_custom_amount,
        ChargeRequestFlow.confirming,
    ),
    F.text == CANCEL_TEXT,
)
async def user_cancel_operation(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(UserMenu.idle)
    await message.answer(
        "عملیات لغو شد.",
        reply_markup=user_main_keyboard(),
    )
