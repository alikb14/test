from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.database import UserRole
from app.keyboards.common import (
    admin_main_keyboard,
    contact_request_keyboard,
    responsible_main_keyboard,
    user_main_keyboard,
)
from app.services import ServiceRegistry
from app.utils.formatters import normalize_phone
from app.utils.states import AdminMenu, AuthState, ResponsibleMenu, UserMenu


router = Router(name="auth")


def _services(message: Message) -> ServiceRegistry:
    services = getattr(message.bot, "services", None)
    if services is None:
        raise RuntimeError("Service registry is not configured on bot instance.")
    return services


async def _enter_role_menu(message: Message, state: FSMContext, role: UserRole) -> None:
    if role is UserRole.ADMIN:
        await state.set_state(AdminMenu.idle)
        await message.answer(
            "🚀 خوش آمدید مدیر عزیز! لطفاً یکی از گزینه‌های منو را انتخاب کنید.",
            reply_markup=admin_main_keyboard(),
        )
    elif role is UserRole.RESPONSIBLE:
        await state.set_state(ResponsibleMenu.idle)
        await message.answer(
            "👋 سلام مسئول محترم! یکی از گزینه‌های زیر را انتخاب کنید.",
            reply_markup=responsible_main_keyboard(),
        )
    else:
        await state.set_state(UserMenu.idle)
        await message.answer(
            "👋 سلام! برای ادامه لطفاً گزینه مورد نظر را انتخاب کنید.",
            reply_markup=user_main_keyboard(),
        )


@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext) -> None:
    services = _services(message)
    await state.clear()

    if message.from_user is None:
        await message.answer("⚠️ برای استفاده از ربات نیاز به حساب کاربری معتبر دارید.")
        return

    existing_user = await services.users.get_by_telegram_id(message.from_user.id)
    if existing_user:
        await _enter_role_menu(message, state, existing_user.role)
        return

    await state.set_state(AuthState.waiting_for_contact)
    await message.answer(
        "📞 لطفاً شماره خود را از طریق دکمه زیر به اشتراک بگذارید.",
        reply_markup=contact_request_keyboard(),
    )


@router.message(AuthState.waiting_for_contact, F.contact)
async def handle_contact(message: Message, state: FSMContext) -> None:
    if message.contact is None or message.from_user is None:
        await message.answer("❌ اطلاعات دریافت‌شده معتبر نیست. دوباره تلاش کنید.")
        return

    if message.contact.user_id != message.from_user.id:
        await message.answer("⚠️ لطفاً فقط شماره خودتان را به اشتراک بگذارید.")
        return

    phone = normalize_phone(message.contact.phone_number)
    services = _services(message)
    user = await services.users.get_by_phone(phone)

    if not user:
        await message.answer(
            "😔 متأسفیم، شماره شما در سیستم ثبت نشده است. با مدیر سیستم تماس بگیرید.",
            reply_markup=contact_request_keyboard(),
        )
        return

    if not user.is_active:
        await message.answer(
            "🚫 حساب کاربری شما غیرفعال شده است. لطفاً جهت رفع مشکل با مدیر سیستم تماس بگیرید.",
            reply_markup=contact_request_keyboard(),
        )
        return

    if user.telegram_id != message.from_user.id:
        await services.users.attach_telegram_account(user, message.from_user.id)

    await _enter_role_menu(message, state, user.role)


@router.message(AuthState.waiting_for_contact)
async def handle_non_contact(message: Message) -> None:
    await message.answer("📞 برای ادامه باید شماره تماس خود را ارسال کنید.")
