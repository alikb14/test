from __future__ import annotations

import contextlib
import logging
from datetime import datetime, timezone
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, FSInputFile, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.exc import IntegrityError, NoResultFound

from app.database import CardType, Department, RequestStatus, RequestType, UserRole
from app.handlers.requests import send_card_to_chat
from app.handlers.utils import Event, get_current_user, get_services, card_type_title, notify_inventory_threshold
from app.keyboards.cards import card_amount_keyboard, card_type_keyboard, calculate_tariff
from app.keyboards.common import (
    admin_cards_menu_keyboard,
    admin_main_keyboard,
    admin_users_menu_keyboard,
    report_selection_keyboard,
    cancel_to_main_keyboard,
    skip_line_expiry_keyboard,
)
from app.keyboards.requests import charge_amount_keyboard
from app.keyboards.users import (
    approval_permission_keyboard,
    department_keyboard,
    line_type_keyboard,
    managers_keyboard,
    user_role_keyboard,
)
from app.utils.formatters import normalize_phone
from app.utils.logger import logger as structured_logger
from app.utils.states import (
    AdminAddCard,
    AdminDefineUser,
    AdminDeleteUser,
    AdminSendCard,
    AdminMenu,
    ChargeRequestFlow,
)


router = Router(name="admin")
logger = logging.getLogger(__name__)

CANCEL_TEXT = "🔙 بازگشت به منوی اصلی"


async def _current_admin(event: Event) -> int | None:
    user = await get_current_user(event)
    return user.id if user else None


ROLE_TITLES = {
    UserRole.ADMIN: "مدیر",
   UserRole.RESPONSIBLE: "مسئول",
    UserRole.USER: "کاربر",
}


def _cleanup_card_entries(entries: list[dict]) -> None:
    for entry in entries:
        if entry.get("type") == "photo":
            file_path = entry.get("file_path")
            if file_path:
                with contextlib.suppress(FileNotFoundError):
                    Path(file_path).unlink()


def _format_user_entry(user) -> str:
    role_label = ROLE_TITLES.get(user.role, getattr(user.role, "value", user.role))
    return f"{user.id}: {user.full_name} ({user.phone}) - {role_label}"


async def _persist_user(event: CallbackQuery, state: FSMContext) -> None:
    services = get_services(event)
    data = await state.get_data()
    phone = data.get("phone")
    full_name = data.get("full_name")
    line_expiry = data.get("line_expiry")
    role_raw = data.get("role")
    line_type_raw = data.get("line_type")

    required_fields = [phone, full_name, role_raw]
    if role_raw != UserRole.RESPONSIBLE.value:
        required_fields.append(line_type_raw)

    if not all(required_fields):
        await event.message.edit_text("اطلاعات ناقص است. عملیات لغو شد.")
        await state.clear()
        await state.set_state(AdminMenu.idle)
        await event.message.answer(
            "به منوی اصلی بازگشتید.",
            reply_markup=admin_main_keyboard(),
        )
        await event.answer()
        return

    role = UserRole(role_raw)
    line_type = CardType(line_type_raw) if line_type_raw else None
    manager_id = data.get("manager_id")
    department_raw = data.get("department")
    department = Department(department_raw) if department_raw else None
    can_approve_directly = data.get("can_approve_directly", False)
    
    if role is UserRole.RESPONSIBLE:
        manager_id = None
        department = None
    else:
        # فقط مسئول می‌تواند مجوز ارسال مستقیم داشته باشد
        can_approve_directly = False

    try:
        user = await services.users.create_user(
            full_name=full_name,
            phone=phone,
            role=role,
            manager_id=manager_id,
            department=department,
            line_expiry=line_expiry,
            line_type=line_type,
            can_approve_directly=can_approve_directly,
        )
    except IntegrityError:
        await event.message.edit_text(
            "کاربری با این شماره یا حساب موجود است. عملیات لغو شد."
        )
        await state.clear()
        await state.set_state(AdminMenu.idle)
        await event.message.answer(
            "به منوی اصلی بازگشتید.",
            reply_markup=admin_main_keyboard(),
        )
        await event.answer()
        return

    await state.clear()
    await state.set_state(AdminMenu.idle)
    await event.message.edit_text(
        f"کاربر جدید با شناسه {user.id} و نقش {user.role.value} ثبت شد."
    )
    await event.message.answer(
        "به منوی اصلی بازگشتید.",
        reply_markup=admin_main_keyboard(),
    )
    await event.answer()


# ==================== منوهای دسته‌بندی شده ====================

@router.message(AdminMenu.idle, F.text == "💳 کارت‌ها")
async def admin_cards_menu(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminMenu.cards_menu)
    await message.answer(
        "💳 منوی مدیریت کارت‌ها\nلطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=admin_cards_menu_keyboard(),
    )


@router.message(AdminMenu.idle, F.text == "👥 کاربرها")
async def admin_users_menu(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminMenu.users_menu)
    await message.answer(
        "👥 منوی مدیریت کاربران\nلطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=admin_users_menu_keyboard(),
    )


@router.message(
    StateFilter(AdminMenu.cards_menu, AdminMenu.users_menu, AdminMenu.reports_menu),
    F.text == CANCEL_TEXT
)
async def admin_back_to_main(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminMenu.idle)
    await message.answer(
        "🔙 بازگشت به منوی اصلی",
        reply_markup=admin_main_keyboard(),
    )


@router.message(
    StateFilter(
        AdminAddCard.choosing_type,
        AdminAddCard.choosing_amount,
        AdminAddCard.waiting_for_image,
        AdminDefineUser.waiting_for_phone,
        AdminDefineUser.waiting_for_line_expiry,
        AdminDefineUser.waiting_for_full_name,
        AdminDefineUser.choosing_role,
        AdminDefineUser.choosing_approval_permission,
        AdminDefineUser.choosing_department,
        AdminDefineUser.choosing_manager,
        AdminDefineUser.choosing_line_type,
        AdminDeleteUser.choosing_user,
        AdminDeleteUser.confirming,
        AdminSendCard.choosing_user,
        AdminSendCard.choosing_card_type,
        AdminSendCard.choosing_amount,
        AdminMenu.reports_menu,
        ChargeRequestFlow.choosing_card_type,
        ChargeRequestFlow.choosing_amount,
        ChargeRequestFlow.waiting_for_custom_amount,
        ChargeRequestFlow.confirming,
    ),
    F.text == CANCEL_TEXT,
)
async def admin_cancel_operation(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    entries: list[dict] = data.get("entries", []) if data else []
    _cleanup_card_entries(entries)
    await state.clear()
    await state.set_state(AdminMenu.idle)
    await message.answer(
        "عملیات لغو شد. به منوی اصلی برگشتید.",
        reply_markup=admin_main_keyboard(),
    )


@router.message(AdminMenu.users_menu, F.text == "❌ حذف کاربر")
async def admin_delete_user_start(message: Message, state: FSMContext) -> None:
    services = get_services(message)
    users = [user for user in await services.users.list_users() if user.is_active]
    if not users:
        await message.answer("کاربری برای حذف وجود ندارد.")
        return

    await state.set_state(AdminDeleteUser.choosing_user)
    await message.answer(
        "شناسه کاربری که باید حذف شود را ارسال کنید. برای لغو از دکمه «🔙 بازگشت به منوی اصلی» استفاده کنید.",
        reply_markup=cancel_to_main_keyboard(),
    )

    lines = ["📋 فهرست کاربران:"]
    for user in sorted(users, key=lambda item: item.full_name):
        lines.append(_format_user_entry(user))

    current_block = lines[0]
    blocks: list[str] = []
    for entry in lines[1:]:
        candidate = f"{current_block}\n{entry}"
        if len(candidate) > 3800:
            blocks.append(current_block)
            current_block = entry
        else:
            current_block = candidate
    if current_block:
        blocks.append(current_block)

    for block in blocks:
        await message.answer(block)


@router.message(StateFilter(AdminDeleteUser.choosing_user))
async def admin_delete_user_choose(message: Message, state: FSMContext) -> None:
    raw_text = (message.text or "").strip()
    if not raw_text.isdigit():
        await message.answer("شناسه کاربر باید به صورت عددی ارسال شود.")
        return

    user_id = int(raw_text)
    services = get_services(message)
    target_user = await services.users.get_by_id(user_id)
    if target_user is None:
        await message.answer("کاربر یافت نشد. لطفاً شناسه دیگری وارد کنید.")
        return
    if target_user.role is UserRole.ADMIN:
        await message.answer("حذف مدیر سیستم مجاز نیست.")
        return
    current_admin = await get_current_user(message)
    if current_admin and current_admin.id == target_user.id:
        await message.answer("امکان حذف حساب کاربری خودتان وجود ندارد.")
        return

    await state.update_data(target_user_id=user_id, target_user_name=target_user.full_name)
    await state.set_state(AdminDeleteUser.confirming)

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ تایید حذف", callback_data="admin_delete_user:confirm")
    builder.button(text="❌ لغو", callback_data="admin_delete_user:cancel")
    builder.adjust(2)

    await message.answer(
        f"آیا از حذف کاربر {target_user.full_name} مطمئن هستید؟",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(StateFilter(AdminDeleteUser.confirming), F.data == "admin_delete_user:cancel")
async def admin_delete_user_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AdminMenu.idle)
    await callback.message.edit_text("عملیات لغو شد.")
    await callback.message.answer(
        "به منوی اصلی بازگشتید.",
        reply_markup=admin_main_keyboard(),
    )
    await callback.answer()


@router.callback_query(StateFilter(AdminDeleteUser.confirming), F.data == "admin_delete_user:confirm")
async def admin_delete_user_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    target_user_id = data.get("target_user_id")
    if target_user_id is None:
        await state.clear()
        await state.set_state(AdminMenu.idle)
        await callback.message.edit_text("اطلاعاتی برای حذف کاربر یافت نشد. عملیات لغو شد.")
        await callback.message.answer(
            "به منوی اصلی بازگشتید.",
            reply_markup=admin_main_keyboard(),
        )
        await callback.answer()
        return

    services = get_services(callback)
    admin_user = await get_current_user(callback)
    try:
        user = await services.users.deactivate_user(target_user_id)
    except NoResultFound:
        await state.clear()
        await state.set_state(AdminMenu.idle)
        await callback.message.edit_text("کاربر انتخاب‌شده دیگر در سیستم وجود ندارد.")
        await callback.message.answer(
            "به منوی اصلی بازگشتید.",
            reply_markup=admin_main_keyboard(),
        )
        await callback.answer()
        return

    structured_logger.log_admin_action(
        action="deactivate_user",
        admin_id=admin_user.id if admin_user else None,
        target_type="user",
        target_user_id=user.id,
    )

    await state.clear()
    await state.set_state(AdminMenu.idle)
    await callback.message.edit_text(f"✅ کاربر {user.full_name} غیرفعال شد.")
    await callback.message.answer(
        "به منوی اصلی بازگشتید.",
        reply_markup=admin_main_keyboard(),
    )
    await callback.answer()


@router.message(AdminMenu.users_menu, F.text == "📤 ارسال کارت برای کاربر")
async def admin_send_card_start(message: Message, state: FSMContext) -> None:
    services = get_services(message)
    users = [user for user in await services.users.list_users() if user.is_active]
    if not users:
        await message.answer("هیچ کاربری برای ارسال کارت وجود ندارد.")
        return

    await state.set_state(AdminSendCard.choosing_user)
    await message.answer(
        "کاربر موردنظر را انتخاب کنید و شناسه او را ارسال نمایید. برای لغو از دکمه «🔙 بازگشت به منوی اصلی» استفاده کنید.",
        reply_markup=cancel_to_main_keyboard(),
    )

    lines = ["📋 لیست کاربران در دسترس:"]
    for user in sorted(users, key=lambda item: item.full_name):
        entry = _format_user_entry(user)
        if not user.telegram_id:
            entry += " (بدون اتصال تلگرام)"
        lines.append(entry)

    blocks: list[str] = []
    current_block = lines[0]
    for entry in lines[1:]:
        candidate = f"{current_block}\n{entry}"
        if len(candidate) > 3800:
            blocks.append(current_block)
            current_block = entry
        else:
            current_block = candidate
    if current_block:
        blocks.append(current_block)

    for block in blocks:
        await message.answer(block)

    await message.answer("شناسه کاربر مدنظر را ارسال کنید تا فرآیند ادامه پیدا کند.")


@router.message(StateFilter(AdminSendCard.choosing_user))
async def admin_send_card_choose_user(message: Message, state: FSMContext) -> None:
    raw_text = (message.text or "").strip()
    if not raw_text.isdigit():
        await message.answer("شناسه کاربر باید به صورت عددی ارسال شود.")
        return

    user_id = int(raw_text)
    services = get_services(message)
    target_user = await services.users.get_by_id(user_id)
    if target_user is None:
        await message.answer("کاربر یافت نشد. لطفاً شناسه دیگری وارد کنید.")
        return
    if not target_user.telegram_id:
        await message.answer(
            "این کاربر هنوز ربات تلگرام را فعال نکرده است و امکان ارسال کارت وجود ندارد. کاربر دیگری را انتخاب کنید."
        )
        return

    await state.update_data(target_user_id=user_id, target_user_name=target_user.full_name)
    await state.set_state(AdminSendCard.choosing_card_type)
    await message.answer(
        f"کاربر {target_user.full_name} انتخاب شد. لطفاً نوع کارت را مشخص کنید.",
        reply_markup=card_type_keyboard(),
    )


@router.callback_query(StateFilter(AdminSendCard.choosing_card_type), F.data.startswith("card_type:"))
async def admin_send_card_type(callback: CallbackQuery, state: FSMContext) -> None:
    _, raw_type = callback.data.split(":", maxsplit=1)
    card_type = CardType(raw_type)
    await state.update_data(card_type=raw_type)
    await state.set_state(AdminSendCard.choosing_amount)
    await callback.message.edit_text(
        f"نوع کارت {card_type_title(card_type)} انتخاب شد. مبلغ کارت را تعیین کنید:",
        reply_markup=card_amount_keyboard(),
    )
    await callback.answer()


@router.callback_query(StateFilter(AdminSendCard.choosing_amount), F.data.startswith("card_amount:"))
async def admin_send_card_amount(callback: CallbackQuery, state: FSMContext) -> None:
    _, raw_amount = callback.data.split(":", maxsplit=1)
    if raw_amount == "custom":
        await callback.answer("ارسال با مبلغ دلخواه پشتیبانی نمی‌شود.", show_alert=True)
        return

    amount = int(raw_amount)
    data = await state.get_data()
    target_user_id = data.get("target_user_id")
    card_type_raw = data.get("card_type")
    if target_user_id is None or card_type_raw is None:
        await state.clear()
        await state.set_state(AdminMenu.users_menu)
        await callback.message.edit_text("اطلاعات عملیات ناقص بود. لطفاً دوباره تلاش کنید.")
        await callback.message.answer(
            "به منوی مدیریت کاربران بازگشتید.",
            reply_markup=admin_users_menu_keyboard(),
        )
        await callback.answer()
        return

    services = get_services(callback)
    target_user = await services.users.get_by_id(target_user_id)
    if target_user is None:
        await state.clear()
        await state.set_state(AdminMenu.users_menu)
        await callback.message.edit_text("کاربر انتخاب‌شده دیگر در سیستم وجود ندارد.")
        await callback.message.answer(
            "به منوی مدیریت کاربران بازگشتید.",
            reply_markup=admin_users_menu_keyboard(),
        )
        await callback.answer()
        return
    if not target_user.telegram_id:
        await callback.message.edit_text("این کاربر دیگر به ربات متصل نیست. عملیات لغو شد.")
        await state.clear()
        await state.set_state(AdminMenu.users_menu)
        await callback.message.answer(
            "به منوی مدیریت کاربران بازگشتید.",
            reply_markup=admin_users_menu_keyboard(),
        )
        await callback.answer()
        return

    operator = await get_current_user(callback)
    actor_id = operator.id if operator else None
    card_type = CardType(card_type_raw)

    await callback.message.edit_text("⏳ در حال ارسال کارت...")
    try:
        card = await services.cards.take_first_available(
            card_type=card_type,
            amount=amount,
            actor_id=actor_id,
        )
    except NoResultFound:
        await callback.message.edit_text(
            f"❌ هیچ کارت {card_type_title(card_type)} با مبلغ {amount:,} دینار در موجودی نیست."
        )
        await callback.message.answer(
            "مبلغ دیگری را انتخاب کنید:",
            reply_markup=card_amount_keyboard(),
        )
        await callback.answer()
        return

    caption = (
        f"✅ کارت {card_type_title(card.card_type)} به مبلغ {card.amount:,} دینار برای شما ارسال شد.\n"
        "ارسال کننده: مدیریت سیستم."
    )
    sent = await send_card_to_chat(
        callback.message.bot,
        services,
        card,
        target_user.telegram_id,
        caption,
    )
    if not sent:
        await services.cards.restore_card(card.id, actor_id=actor_id)
        await callback.message.edit_text("ارسال کارت با خطا مواجه شد. کمی بعد دوباره تلاش کنید.")
        await callback.answer()
        return
    try:
        request = await services.requests.create_request(
            requester_id=target_user.id,
            responsible_id=None,
            amount=card.amount,
            request_type=RequestType.FIXED,
            status=RequestStatus.PENDING_MANAGER,
            card_type=card.card_type,
        )
        await services.requests.attach_card(
            request_id=request.id,
            card_id=card.id,
            actor_id=actor_id,
        )
        await services.requests.set_status(
            request.id,
            actor_id=actor_id,
            new_status=RequestStatus.APPROVED,
            note="Direct admin send",
        )
        if actor_id:
            await services.requests.set_approver(request.id, actor_id)
    except Exception:
        await services.cards.restore_card(card.id, actor_id=actor_id)
        logger.exception("Failed to register direct admin card send")
        await callback.message.edit_text(
            "ارسال کارت ثبت نشد. لطفاً دوباره تلاش کنید."
        )
        await callback.answer()
        return

    await services.cards.mark_sent(card.id, actor_id=actor_id)
    await notify_inventory_threshold(
        callback.message.bot,
        services,
        card.card_type,
        card.amount,
        exclude_user_id=actor_id,
    )

    if operator:
        structured_logger.log_admin_action(
            action="send_card_direct",
            admin_id=operator.id,
            target_type="user",
            target_user_id=target_user.id,
            card_type=card.card_type.value,
            amount=card.amount,
            card_id=card.id,
        )

    admins = await services.users.list_admins()
    info_message = (
        f"ادمین {operator.full_name if operator else 'سیستم'} کارت {card_type_title(card.card_type)}"
        f" به مبلغ {card.amount:,} دینار را برای {target_user.full_name} ارسال کرد."
    )
    for other_admin in admins:
        if not other_admin.telegram_id:
            continue
        if operator and other_admin.id == operator.id:
            continue
        await callback.message.bot.send_message(other_admin.telegram_id, info_message)

    await state.clear()
    await state.set_state(AdminMenu.idle)
    await callback.message.edit_text("عملیات ارسال کارت تکمیل شد.")
    await callback.message.answer(
        f"✅ کارت {card_type_title(card.card_type)} به مبلغ {card.amount:,} دینار برای {target_user.full_name} ارسال شد.",
        reply_markup=admin_main_keyboard(),
    )
    await callback.answer()


# ==================== handler های کارت ====================

@router.message(AdminMenu.cards_menu, F.text == "➕ افزودن کارت")
async def admin_add_card(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminAddCard.choosing_type)
    await message.answer(
        "یکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=card_type_keyboard(),
    )


@router.callback_query(StateFilter(AdminAddCard.choosing_type), F.data.startswith("card_type:"))
async def admin_add_card_type(callback: CallbackQuery, state: FSMContext) -> None:
    _, raw_type = callback.data.split(":", maxsplit=1)
    await state.update_data(card_type=raw_type)
    await state.set_state(AdminAddCard.choosing_amount)
    await callback.message.edit_text(
        "💰 لطفاً مبلغ کارت را انتخاب کنید.",
        reply_markup=card_amount_keyboard(),
    )
    await callback.answer()


@router.callback_query(StateFilter(AdminAddCard.choosing_amount), F.data.startswith("card_amount:"))
async def admin_add_card_amount(callback: CallbackQuery, state: FSMContext) -> None:
    _, raw_amount = callback.data.split(":", maxsplit=1)
    if raw_amount == "custom":
        await callback.answer("مبالغ دلخواه برای افزودن کارت فعلاً پشتیبانی نمی‌شود.", show_alert=True)
        return
    previous_data = await state.get_data()
    if previous_data and previous_data.get("entries"):
        _cleanup_card_entries(previous_data.get("entries", []))

    await state.update_data(
        amount=int(raw_amount),
        entries=[],
    )
    await state.set_state(AdminAddCard.waiting_for_image)
    await callback.message.edit_reply_markup()
    await callback.message.answer(
        "📷 لطفاً عکس یا سریال‌نامبر کارت شارژ را ارسال کنید.\n"
        "برای ارسال چند سریال می‌توانید از فاصله یا ویرگول استفاده کنید.\n"
        "برای پایان، کلمه «تمام» را بفرستید.",
        reply_markup=cancel_to_main_keyboard(),
    )
    await callback.answer()

@router.message(StateFilter(AdminAddCard.waiting_for_image), F.photo)
async def admin_add_card_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    card_type_raw = data.get("card_type")
    amount = data.get("amount")
    if not card_type_raw or not amount:
        await message.answer("اطلاعات کارت ناقص است. دوباره تلاش کنید.")
        await state.clear()
        await state.set_state(AdminMenu.idle)
        await message.answer("به منوی اصلی بازگشتید.", reply_markup=admin_main_keyboard())
        return

    card_type = CardType(card_type_raw)
    amount_int = int(amount)
    entries: list[dict] = data.get("entries", [])

    photo = message.photo[-1]
    if any(
        entry.get("type") == "photo" and entry.get("file_unique_id") == photo.file_unique_id
        for entry in entries
    ):
        await message.answer("این تصویر قبلاً ثبت شده است. لطفاً تصویر دیگری ارسال کنید یا «تمام» را بفرستید.")
        return

    services = get_services(message)
    media_dir = services.cards.media_root / card_type.value / str(amount_int)
    media_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{photo.file_unique_id}.jpg"
    file_path = media_dir / filename
    try:
        await message.bot.download(file=photo, destination=file_path)
    except Exception:
        logger.exception("Failed to download card photo")
        await message.answer(
            "ذخیره تصویر کارت با خطا مواجه شد. لطفاً دوباره تلاش کنید یا از دکمه «🔙 بازگشت به منوی اصلی» استفاده کنید.",
        )
        return

    entries.append(
        {
            "type": "photo",
            "file_id": photo.file_id,
            "file_unique_id": photo.file_unique_id,
            "file_path": str(file_path.resolve()),
        }
    )
    await state.update_data(entries=entries)

    await message.answer(
        f"✅ عکس ثبت شد. مجموع کارت‌های ثبت‌شده: {len(entries)}.\n"
        "برای افزودن کارت دیگر، عکس یا سریال‌نامبر ارسال کنید؛ برای پایان، کلمه «تمام» را بفرستید.",
        reply_markup=cancel_to_main_keyboard(),
    )


@router.message(StateFilter(AdminAddCard.waiting_for_image), F.text)
async def admin_add_card_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    card_type_raw = data.get("card_type")
    amount = data.get("amount")
    if not card_type_raw or not amount:
        await message.answer("اطلاعات کارت ناقص است. دوباره تلاش کنید.")
        await state.clear()
        await state.set_state(AdminMenu.idle)
        await message.answer("به منوی اصلی بازگشتید.", reply_markup=admin_main_keyboard())
        return

    text = (message.text or "").strip()
    if not text:
        await message.answer("متن دریافت نشد. لطفاً سریال‌نامبر را وارد کنید یا عکس ارسال نمایید.")
        return

    entries: list[dict] = data.get("entries", [])

    if text.lower() == "تمام":
        if not entries:
            await message.answer("هنوز کارتی ثبت نشده است. ابتدا عکس یا سریال‌نامبر ارسال کنید.")
            return

        card_type = CardType(card_type_raw)
        count = len(entries)
        confirm_text = (
            f"آیا از اضافه کردن {count} کارت {int(amount):,} دینار {card_type_title(card_type)} مطمئن هستید؟"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ تایید", callback_data="admin_add_cards:confirm")
        builder.button(text="❌ لغو", callback_data="admin_add_cards:cancel")
        builder.adjust(2)
        await state.update_data(entries=entries)
        await state.set_state(AdminAddCard.confirming)
        await message.answer(confirm_text, reply_markup=builder.as_markup())
        return

    serial_candidates = []
    for line in text.replace("،", ",").replace("؛", ",").splitlines():
        for chunk in line.split(","):
            serial_candidates.extend(part for part in chunk.split() if part)
    serials = [candidate for candidate in serial_candidates if candidate]

    if not serials:
        await message.answer("سریال‌نامبر معتبری تشخیص داده نشد. لطفاً مجدداً تلاش کنید.")
        return

    processed = 0
    duplicates: list[str] = []
    for serial in serials:
        if any(entry.get("type") == "serial" and entry.get("serial") == serial for entry in entries):
            duplicates.append(serial)
            continue
        entries.append({"type": "serial", "serial": serial})
        processed += 1

    if processed == 0:
        await message.answer("همه سریال‌های ارسال‌شده تکراری بودند. لطفاً سریال جدیدی وارد کنید.")
        return

    await state.update_data(entries=entries)
    response_lines = [
        f"✅ {processed} سریال ثبت شد. مجموع کارت‌های ثبت‌شده: {len(entries)}.",
        "برای افزودن بیشتر عکس یا سریال‌نامبر دیگری ارسال کنید؛ برای پایان، کلمه «تمام» را بفرستید.",
    ]
    if duplicates:
        response_lines.insert(1, "سریال‌های تکراری نادیده گرفته شدند.")
    await message.answer("\n".join(response_lines), reply_markup=cancel_to_main_keyboard())


@router.message(StateFilter(AdminAddCard.waiting_for_image))
async def admin_add_card_invalid(message: Message) -> None:
    await message.answer(
        "لطفاً عکس یا سریال‌نامبر معتبر ارسال کنید یا با دکمه «🔙 بازگشت به منوی اصلی» عملیات را لغو کنید.",
    )


@router.callback_query(StateFilter(AdminAddCard.confirming), F.data == "admin_add_cards:cancel")
async def admin_add_cards_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    entries: list[dict] = data.get("entries", [])
    _cleanup_card_entries(entries)
    await state.clear()
    await state.set_state(AdminMenu.idle)
    await callback.message.edit_text("عملیات لغو شد.")
    await callback.message.answer(
        "به منوی اصلی بازگشتید.",
        reply_markup=admin_main_keyboard(),
    )
    await callback.answer()


@router.callback_query(StateFilter(AdminAddCard.confirming), F.data == "admin_add_cards:confirm")
async def admin_add_cards_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    entries: list[dict] = data.get("entries", [])
    card_type_raw = data.get("card_type")
    amount_raw = data.get("amount")
    if not card_type_raw or amount_raw is None:
        _cleanup_card_entries(entries)
        await state.clear()
        await state.set_state(AdminMenu.idle)
        await callback.message.edit_text("اطلاعات کارت ناقص بود. عملیات لغو شد.")
        await callback.message.answer(
            "به منوی اصلی بازگشتید.",
            reply_markup=admin_main_keyboard(),
        )
        await callback.answer()
        return

    card_type = CardType(card_type_raw)
    amount = int(amount_raw)
    services = get_services(callback)
    actor_id = await _current_admin(callback)
    base_dir = services.cards.media_root.parent

    count = len(entries)

    try:
        for entry in entries:
            if entry.get("type") == "photo":
                file_path = Path(entry["file_path"]).resolve()
                try:
                    relative_path = str(file_path.relative_to(base_dir))
                except ValueError:
                    relative_path = str(file_path)
                await services.cards.add_card(
                    card_type=card_type,
                    amount=amount,
                    actor_id=actor_id,
                    image_file_id=entry["file_id"],
                    image_path=relative_path,
                )
            else:
                await services.cards.add_card(
                    card_type=card_type,
                    amount=amount,
                    actor_id=actor_id,
                    serial_number=entry["serial"],
                )
    except IntegrityError:
        await state.set_state(AdminAddCard.waiting_for_image)
        await callback.message.edit_text(
            "❌ افزودن کارت با خطا مواجه شد. احتمالاً سریال‌نامبر تکراری است. لطفاً بررسی کنید و دوباره تلاش کنید."
        )
        await callback.answer()
        return
    except Exception:
        logger.exception("Failed to add cards batch")
        await state.clear()
        await state.set_state(AdminMenu.idle)
        await callback.message.edit_text(
            "❌ افزودن کارت‌ها با خطای غیرمنتظره مواجه شد. لطفاً موجودی را بررسی کنید و در صورت نیاز عملیات را دوباره انجام دهید."
        )
        await callback.message.answer(
            "به منوی اصلی بازگشتید.",
            reply_markup=admin_main_keyboard(),
        )
        await callback.answer()
        return

    structured_logger.log_admin_action(
        action="add_cards_batch",
        admin_id=actor_id,
        target_type="card",
        card_type=card_type.value,
        amount=amount,
        count=count,
    )

    await state.clear()
    await state.set_state(AdminMenu.idle)
    await callback.message.edit_text(
        f"✅ {count} کارت {amount:,} دینار {card_type_title(card_type)} با موفقیت اضافه شد."
    )
    await callback.message.answer(
        "به منوی اصلی بازگشتید.",
        reply_markup=admin_main_keyboard(),
    )
    await callback.answer()


@router.message(StateFilter(AdminMenu.idle, AdminMenu.cards_menu), F.text == "📋 لیست کارت‌ها")
async def admin_list_cards(message: Message) -> None:
    services = get_services(message)
    summary = await services.cards.available_summary()
    if not summary:
        await message.answer("💳 هیچ کارت فعالی در موجودی ثبت نشده است.")
        return

    lines = ["📋 موجودی کارت‌ها:"]
    for card_type, amounts in summary.items():
        lines.append(f"نوع {card_type}:")
        for amount, count in sorted(amounts.items()):
            lines.append(f"  مبلغ {amount:,} دینار: {count} عدد")
    await message.answer("\n".join(lines))


@router.message(AdminMenu.idle, F.text == "📊 گزارش ها")
async def admin_reports_menu(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminMenu.reports_menu)
    await message.answer(
        "نوع گزارش مورد نظر را انتخاب کنید:",
        reply_markup=report_selection_keyboard(),
    )


@router.message(AdminMenu.reports_menu, F.text == "📊 گزارش کارت‌ها")
async def admin_report_cards_summary(message: Message) -> None:
    services = get_services(message)
    now = datetime.now(timezone.utc)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    records = await services.requests.export_consumed_requests(
        start=start_of_month,
        end=now,
    )
    if not records:
        await message.answer(
            "📅 در این ماه کارت مصرف‌شده‌ای ثبت نشده است.",
            reply_markup=report_selection_keyboard(),
        )
        return

    import pandas as pd

    df = pd.DataFrame(records)
    df["updated_at"] = pd.to_datetime(df["updated_at"], utc=True).dt.tz_convert(
        "Asia/Tehran"
    ).dt.strftime("%Y-%m-%d %H:%M")
    df["type"] = df["type"].map({"fixed": "مبلغ ثابت", "custom": "مبلغ دلخواه"})
    df["tariff"] = df["amount"].apply(calculate_tariff)
    df["sender"] = df["approver"].fillna(df["responsible"])
    df["sender"] = df["sender"].fillna("—")
    df.rename(
        columns={
            "id": "شناسه",
            "amount": "مبلغ",
            "tariff": "تعرفه واقعی",
            "type": "نوع درخواست",
            "updated_at": "تاریخ ارسال",
            "requester": "درخواست‌کننده",
            "approver": "تایید‌کننده",
            "responsible": "مسئول",
            "sender": "ارسال‌کننده",
        },
        inplace=True,
    )

    total_amount = int(df["مبلغ"].sum())
    total_tariff = int(df["تعرفه واقعی"].sum())
    count = len(df)
    type_summary = df.groupby("نوع درخواست")["مبلغ"].sum().to_dict()

    reports_dir = services.cards.media_root.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    file_path = reports_dir / "consumed_cards.xlsx"
    df.to_excel(file_path, index=False)

    summary_lines = [
        f"📊 تعداد کارت‌های مصرف‌شده: {count}",
        f"💰 مجموع مبالغ اسمی: {total_amount:,} دینار",
        f"💵 مجموع تعرفه واقعی: {total_tariff:,} دینار",
    ]
    for label, amount in type_summary.items():
        summary_lines.append(f"{label}: {amount:,} دینار")

    await message.answer("\n".join(summary_lines), reply_markup=report_selection_keyboard())
    await message.answer_document(
        FSInputFile(str(file_path)),
        caption="گزارش کارت‌های مصرف‌شده (اکسل).",
    )


@router.message(AdminMenu.reports_menu, F.text == "👥 گزارش مصرف کاربرها")
async def admin_report_user_consumption(message: Message) -> None:
    services = get_services(message)
    now = datetime.now(timezone.utc)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    records = await services.requests.export_consumed_requests(
        start=start_of_month,
        end=now,
    )
    if not records:
        await message.answer(
            "📅 در این ماه کارت مصرف‌شده‌ای ثبت نشده است.",
            reply_markup=report_selection_keyboard(),
        )
        return

    import pandas as pd

    df = pd.DataFrame(records)
    df["tariff"] = df["amount"].apply(calculate_tariff)
    grouped = (
        df.groupby("requester")
        .agg(تعداد=("id", "count"), مبلغ_اسمی=("amount", "sum"), تعرفه_واقعی=("tariff", "sum"))
        .reset_index()
        .rename(columns={"requester": "کاربر"})
    )
    grouped["تعداد"] = grouped["تعداد"].astype(int)
    grouped["مبلغ_اسمی"] = grouped["مبلغ_اسمی"].astype(int)
    grouped["تعرفه_واقعی"] = grouped["تعرفه_واقعی"].astype(int)

    reports_dir = services.cards.media_root.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    file_path = reports_dir / "consumed_users.xlsx"
    grouped.to_excel(file_path, index=False)

    total_amount = int(grouped["مبلغ_اسمی"].sum())
    total_tariff = int(grouped["تعرفه_واقعی"].sum())
    total_count = int(grouped["تعداد"].sum())

    lines = ["👥 گزارش مصرف کاربران:"]
    for idx, row in grouped.iterrows():
        lines.append(
            f"{idx + 1}. {row['کاربر']}: تعداد {int(row['تعداد'])}, مبلغ اسمی {int(row['مبلغ_اسمی']):,} دینار، "
            f"تعرفه واقعی {int(row['تعرفه_واقعی']):,} دینار"
        )
    lines.append("")
    lines.append(f"🔢 مجموع کارت‌ها: {total_count}")
    lines.append(f"💰 مجموع مبالغ اسمی: {total_amount:,} دینار")
    lines.append(f"💵 مجموع تعرفه واقعی: {total_tariff:,} دینار")

    await message.answer("\n".join(lines), reply_markup=report_selection_keyboard())
    await message.answer_document(
        FSInputFile(str(file_path)),
        caption="گزارش مصرف کاربران (اکسل).",
    )


@router.message(StateFilter(AdminMenu.idle, AdminMenu.users_menu), F.text == "👤 تعریف کاربر جدید")
async def admin_define_user(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminDefineUser.waiting_for_phone)
    await message.answer(
        "📞 شماره تلفن کاربر را ارسال کنید (با پیش‌شماره).",
        reply_markup=cancel_to_main_keyboard(),
    )


@router.message(StateFilter(AdminDefineUser.waiting_for_phone))
async def admin_define_user_phone(message: Message, state: FSMContext) -> None:
    phone = normalize_phone(message.text or "")
    # بررسی فرمت شماره تلفن: +xxxxxxxxxxxxx
    import re
    if not re.match(r'^\+\d{10,15}$', phone):
        await message.answer(
            "❌ فرمت شماره تلفن نامعتبر است!\n"
            "📞 فرمت صحیح: +xxxxxxxxxxxxx\n"
            "مثال: +964770123456۷",
        )
        return

    services = get_services(message)
    existing_user = await services.users.get_by_phone(phone)
    if existing_user:
        await message.answer(
            "این شماره قبلاً در سیستم ثبت شده است. لطفاً شماره دیگری وارد کنید یا به منوی اصلی برگردید.",
            reply_markup=cancel_to_main_keyboard(),
        )
        return

    await state.update_data(phone=phone)
    await state.set_state(AdminDefineUser.waiting_for_line_expiry)
    await message.answer(
        "📅 تاریخ صلاحیت خط را به صورت YYYY-MM-DD یا YYYY/MM/DD ارسال کنید.\n"
        "مثال: 2025-12-31 یا 2025/12/31\n\n"
        "⚠️ توجه: روز و ماه باید دو رقمی باشند",
        reply_markup=skip_line_expiry_keyboard(),
    )


@router.message(StateFilter(AdminDefineUser.waiting_for_line_expiry))
async def admin_define_user_line_expiry(message: Message, state: FSMContext) -> None:
    raw_date = (message.text or "").strip()
    line_expiry = None
    
    # بررسی skip - فقط با استفاده از دکمه keyboard
    if raw_date == "⏭️ رد کردن تاریخ صلاحیت":
        line_expiry = None
    elif raw_date:
        # بررسی فرمت دقیق
        import re
        # فرمت‌های مجاز: YYYY-MM-DD یا YYYY/MM/DD (دقیقاً دو رقمی)
        if re.match(r'^\d{4}-\d{2}-\d{2}$', raw_date):
            try:
                line_expiry = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                await message.answer(
                    "❌ تاریخ نامعتبر است!\n"
                    "📅 فرمت صحیح: YYYY-MM-DD\n"
                    "مثال: 2025-12-31 (روز و ماه باید دو رقمی باشند)",
                    reply_markup=skip_line_expiry_keyboard(),
                )
                return
        elif re.match(r'^\d{4}/\d{2}/\d{2}$', raw_date):
            try:
                line_expiry = datetime.strptime(raw_date, "%Y/%m/%d").date()
            except ValueError:
                await message.answer(
                    "❌ تاریخ نامعتبر است!\n"
                    "📅 فرمت صحیح: YYYY/MM/DD\n"
                    "مثال: 2025/12/31 (روز و ماه باید دو رقمی باشند)",
                    reply_markup=skip_line_expiry_keyboard(),
                )
                return
        else:
            await message.answer(
                "❌ فرمت تاریخ نامعتبر است!\n"
                "📅 فرمت صحیح: YYYY-MM-DD یا YYYY/MM/DD\n"
                "مثال: 2025-12-31 یا 2025/12/31\n"
                "⚠️ توجه: روز و ماه باید دو رقمی باشند (04 نه 4)",
                reply_markup=skip_line_expiry_keyboard(),
            )
            return
        
        # بررسی اینکه تاریخ از امروز جلوتر باشد
        from datetime import date
        if line_expiry and line_expiry < date.today():
            await message.answer(
                "❌ تاریخ انقضا نمی‌تواند مربوط به گذشته باشد.\n"
                "لطفاً تاریخی از امروز به بعد وارد کنید.",
                reply_markup=skip_line_expiry_keyboard(),
            )
            return
    
    await state.update_data(line_expiry=line_expiry)
    await state.set_state(AdminDefineUser.waiting_for_full_name)
    await message.answer(
        "👤 نام کامل کاربر را ارسال کنید.",
    )


@router.message(StateFilter(AdminDefineUser.waiting_for_full_name))
async def admin_define_user_full_name(message: Message, state: FSMContext) -> None:
    await state.update_data(full_name=message.text)
    await state.set_state(AdminDefineUser.choosing_role)
    await message.answer(
        "👥 سمت کاربر را انتخاب کنید.",
        reply_markup=user_role_keyboard(),
    )


@router.callback_query(StateFilter(AdminDefineUser.choosing_role), F.data.startswith("user_role:"))
async def admin_define_user_role(callback: CallbackQuery, state: FSMContext) -> None:
    _, role = callback.data.split(":", maxsplit=1)
    await state.update_data(role=role)
    
    if role == UserRole.RESPONSIBLE.value:
        # برای مسئول، بپرس که آیا مجوز ارسال مستقیم دارد یا نه
        await state.set_state(AdminDefineUser.choosing_approval_permission)
        await callback.message.edit_text(
            "آیا این مسئول مجوز ارسال مستقیم کارت را دارد؟\n"
            "(با مجوز ارسال مستقیم، مسئول می‌تواند بدون نیاز به تایید ادمین، کارت را به کاربران ارسال کند)",
            reply_markup=approval_permission_keyboard(),
        )
        await callback.answer()
        return

    await state.set_state(AdminDefineUser.choosing_department)
    await callback.message.edit_text(
        "بخش کاربر را انتخاب کنید.",
        reply_markup=department_keyboard(),
    )
    await callback.answer()


@router.callback_query(StateFilter(AdminDefineUser.choosing_approval_permission), F.data.startswith("approval_permission:"))
async def admin_define_approval_permission(callback: CallbackQuery, state: FSMContext) -> None:
    _, permission = callback.data.split(":", maxsplit=1)
    can_approve = permission == "yes"
    await state.update_data(can_approve_directly=can_approve)
    await _persist_user(callback, state)


@router.callback_query(
    StateFilter(AdminDefineUser.choosing_department), F.data.startswith("department:")
)
async def admin_define_user_department(callback: CallbackQuery, state: FSMContext) -> None:
    _, department = callback.data.split(":", maxsplit=1)
    await state.update_data(department=department)
    services = get_services(callback)
    responsibles = await services.users.list_responsibles()
    if not responsibles:
        await callback.message.edit_text(
            "هیچ مسئول فعالی یافت نشد. ابتدا یک مسئول ایجاد کنید.",
        )
        await state.clear()
        await state.set_state(AdminMenu.idle)
        await callback.message.answer(
            "بازگشت به منوی اصلی.",
            reply_markup=admin_main_keyboard(),
        )
        await callback.answer()
        return

    await state.set_state(AdminDefineUser.choosing_manager)
    await callback.message.edit_text(
        "مسئول کاربر را انتخاب کنید.",
        reply_markup=managers_keyboard(responsibles),
    )
    await callback.answer()


@router.callback_query(
    StateFilter(AdminDefineUser.choosing_manager), F.data.startswith("manager:")
)
async def admin_define_user_manager(callback: CallbackQuery, state: FSMContext) -> None:
    _, manager_id = callback.data.split(":", maxsplit=1)
    await state.update_data(manager_id=int(manager_id))
    
    # اضافه کردن مرحله انتخاب نوع خط
    await state.set_state(AdminDefineUser.choosing_line_type)
    await callback.message.edit_text(
        "📱 نوع خط کاربر را انتخاب کنید.",
        reply_markup=line_type_keyboard(),
    )
    await callback.answer()


@router.callback_query(
    StateFilter(AdminDefineUser.choosing_line_type), F.data.startswith("line_type:")
)
async def admin_define_user_line_type(callback: CallbackQuery, state: FSMContext) -> None:
    _, line_type = callback.data.split(":", maxsplit=1)
    await state.update_data(line_type=line_type)
    await _persist_user(callback, state)


@router.message(StateFilter(AdminMenu.idle, AdminMenu.users_menu), F.text == "👥 لیست کاربرها")
async def admin_list_users(message: Message) -> None:
    services = get_services(message)
    users_data = await services.users.export_users()
    if not users_data:
        await message.answer("👥 کاربری برای نمایش وجود ندارد.")
        return

    role_map = {
        UserRole.ADMIN.value: "مدیر",
        UserRole.RESPONSIBLE.value: "مسئول",
        UserRole.USER.value: "کاربر",
    }
    department_map = {
        "network": "شبکه",
        "institute": "مؤسسه",
    }

    entries: list[str] = []
    for idx, user in enumerate(users_data, start=1):
        role_label = role_map.get(user.get("role"), user.get("role", ""))
        dept_label = department_map.get(user.get("department"), "—")
        manager_label = user.get("manager") or "—"
        status_label = "فعال" if user.get("is_active") else "غیرفعال"
        line_expiry = user.get("line_expiry")
        line_label = line_expiry.strftime("%Y-%m-%d") if line_expiry else "—"
        entries.append(
            f"{idx}. {user.get('full_name')} ({user.get('phone')})\n"
            f"   سمت: {role_label} | بخش: {dept_label} | مسئول: {manager_label}\n"
            f"   وضعیت: {status_label} | اعتبار خط: {line_label}"
        )

    header = f"لیست کاربرها (تعداد: {len(users_data)}):"
    message_blocks: list[str] = []
    current_block = header
    for entry in entries:
        candidate = f"{current_block}\n{entry}"
        if len(candidate) > 3800:
            message_blocks.append(current_block)
            current_block = entry
        else:
            current_block = candidate
    if current_block:
        message_blocks.append(current_block)

    for block in message_blocks:
        await message.answer(block)

    import pandas as pd

    df = pd.DataFrame(users_data)
    if "line_expiry" in df.columns:
        df["line_expiry"] = df["line_expiry"].astype(str)
    df["is_active"] = df["is_active"].map({True: "فعال", False: "غیرفعال"})
    df.rename(
        columns={
            "full_name": "نام",
            "phone": "شماره",
            "role": "سمت",
            "department": "بخش",
            "line_expiry": "تاریخ اعتبار خط",
            "manager": "مسئول",
            "is_active": "وضعیت",
        },
        inplace=True,
    )

    reports_dir = services.cards.media_root.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    file_path = reports_dir / "users.xlsx"
    df.to_excel(file_path, index=False)

    await message.answer_document(
        FSInputFile(str(file_path)),
        caption="📄 لیست کاربرها به صورت فایل اکسل ارسال شد.",
    )


def get_charge_amount_keyboard() -> InlineKeyboardMarkup:
    """Create a keyboard with charge amount buttons"""
    builder = InlineKeyboardBuilder()
    for amount in (2000, 5000, 6000, 10000, 15000, 20000, 25000, 30000, 40000, 50000, 100000):
        builder.button(text=f"💰 {amount:,}", callback_data=f"charge_amount:{amount}")
    builder.button(text="✏️ مبلغ دلخواه", callback_data="charge_amount:custom")
    builder.adjust(3, 3, 3, 2, 1)
    return builder.as_markup()

@router.callback_query(StateFilter(ChargeRequestFlow.choosing_card_type), F.data.startswith("card_type:"))
async def admin_charge_card_type_selected(callback: CallbackQuery, state: FSMContext) -> None:
    _, card_type_str = callback.data.split(":")
    card_type = CardType(card_type_str)
    await state.update_data(card_type=card_type.value)
    await state.set_state(ChargeRequestFlow.choosing_amount)
    await callback.message.edit_text("نوع کارت انتخاب شد.")
    await callback.message.answer(
        "لطفاً مبلغ شارژ را انتخاب کنید.",
        reply_markup=cancel_to_main_keyboard(),
    )
    await callback.message.answer(
        "یکی از مبالغ زیر را انتخاب کنید:",
        reply_markup=get_charge_amount_keyboard(),
    )
    await callback.answer()

@router.message(AdminMenu.idle, F.text == "🔋 درخواست شارژ")
async def admin_request_charge(message: Message, state: FSMContext) -> None:
    await state.set_state(ChargeRequestFlow.choosing_card_type)
    await state.update_data(origin="admin")
    await message.answer(
        "یکی از گزینه‌های کارت را انتخاب کنید:",
        reply_markup=card_type_keyboard(),
    )

