from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message
from sqlalchemy.exc import NoResultFound

from app.database import CardType, RequestStatus, RequestType, UserRole
from app.handlers.utils import (
    card_type_title,
    get_current_user,
    get_services,
    notify_inventory_threshold,
)
from app.handlers.requests import notify_accounting, send_card_to_chat
from app.keyboards.common import cancel_to_main_keyboard, report_selection_keyboard, responsible_main_keyboard
from app.keyboards.requests import charge_amount_keyboard
from app.keyboards.cards import calculate_tariff, card_amount_keyboard, card_type_keyboard
from app.utils.states import ChargeRequestFlow, ResponsibleMenu, ResponsibleSendCard
from app.utils.logger import logger as structured_logger


router = Router(name="responsible")
logger = logging.getLogger(__name__)
CANCEL_TEXT = "🔙 بازگشت به منوی اصلی"


@router.message(ResponsibleMenu.idle, F.text == "📊 گزارش ها")
async def responsible_reports_menu(message: Message, state: FSMContext) -> None:
    services = get_services(message)
    current_user = await get_current_user(message)
    if current_user is None or current_user.role is not UserRole.RESPONSIBLE:
        await message.answer("⚠️ دسترسی مشاهده گزارش برای شما فعال نیست.")
        return

    await state.set_state(ResponsibleMenu.reports_menu)
    await message.answer(
        "نوع گزارش مورد نظر را انتخاب کنید:",
        reply_markup=report_selection_keyboard(),
    )


@router.message(ResponsibleMenu.reports_menu, F.text == "📊 گزارش کارت‌ها")
async def responsible_report_cards(message: Message) -> None:
    services = get_services(message)
    current_user = await get_current_user(message)
    if current_user is None or current_user.role is not UserRole.RESPONSIBLE:
        await message.answer("⚠️ دسترسی ندارید.", reply_markup=report_selection_keyboard())
        return

    now = datetime.now(timezone.utc)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    records = await services.requests.export_consumed_requests(
        responsible_id=current_user.id,
        start=start_of_month,
        end=now,
    )
    if not records:
        await message.answer(
            "📅 در این ماه مصرفی برای زیرمجموعه شما ثبت نشده است.",
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
            "responsible": "مسئول",
            "approver": "تایید‌کننده",
            "sender": "ارسال‌کننده",
        },
        inplace=True,
    )

    total_amount = int(df["مبلغ"].sum())
    total_tariff = int(df["تعرفه واقعی"].sum())
    count = len(df)

    reports_dir = services.cards.media_root.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    file_path = reports_dir / f"consumed_resp_{current_user.id}.xlsx"
    df.to_excel(file_path, index=False)

    summary = (
        f"📊 تعداد کارت‌های مصرف‌شده: {count}\n"
        f"💰 مجموع مبالغ اسمی: {total_amount:,} دینار\n"
        f"💵 مجموع تعرفه واقعی: {total_tariff:,} دینار"
    )

    await message.answer(summary, reply_markup=report_selection_keyboard())
    await message.answer_document(
        FSInputFile(str(file_path)),
        caption="📈 گزارش مصرف کارت‌های زیرمجموعه (اکسل).",
    )


@router.message(ResponsibleMenu.reports_menu, F.text == "👥 گزارش مصرف کاربرها")
async def responsible_report_user_consumption(message: Message) -> None:
    services = get_services(message)
    current_user = await get_current_user(message)
    if current_user is None or current_user.role is not UserRole.RESPONSIBLE:
        await message.answer("⚠️ دسترسی ندارید.", reply_markup=report_selection_keyboard())
        return

    now = datetime.now(timezone.utc)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    records = await services.requests.export_consumed_requests(
        responsible_id=current_user.id,
        start=start_of_month,
        end=now,
    )
    if not records:
        await message.answer(
            "📅 در این ماه مصرفی برای زیرمجموعه شما ثبت نشده است.",
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
    file_path = reports_dir / f"consumed_users_resp_{current_user.id}.xlsx"
    grouped.to_excel(file_path, index=False)

    total_amount = int(grouped["مبلغ_اسمی"].sum())
    total_tariff = int(grouped["تعرفه_واقعی"].sum())
    total_count = int(grouped["تعداد"].sum())

    lines = ["👥 گزارش مصرف کاربران زیرمجموعه:"]
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
        caption="گزارش مصرف کاربران زیرمجموعه (اکسل).",
    )


@router.message(ResponsibleMenu.idle, F.text == "👥 لیست کاربرها")
async def responsible_user_list(message: Message) -> None:
    services = get_services(message)
    current_user = await get_current_user(message)
    if current_user is None or current_user.role is not UserRole.RESPONSIBLE:
        await message.answer("⚠️ دسترسی مشاهده لیست برای شما فعال نیست.")
        return

    users_data = await services.users.export_users(manager_id=current_user.id)
    if not users_data:
        await message.answer("👥 هیچ کاربری در زیرمجموعه شما ثبت نشده است.")
        return

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
    file_path = reports_dir / f"subordinates_{current_user.id}.xlsx"
    df.to_excel(file_path, index=False)

    await message.answer_document(
        FSInputFile(str(file_path)),
        caption="📄 لیست کاربران زیرمجموعه ارسال شد.",
    )



@router.message(ResponsibleMenu.idle, F.text == "📤 ارسال کارت برای کاربر")
async def responsible_send_card_start(message: Message, state: FSMContext) -> None:
    services = get_services(message)
    current_user = await get_current_user(message)
    if current_user is None or current_user.role is not UserRole.RESPONSIBLE:
        await message.answer("⚠️ دسترسی لازم برای این عملیات را ندارید.")
        return

    members = [user for user in await services.users.list_members(current_user.id) if user.is_active]
    if not members:
        await message.answer("👥 هیچ کاربری در زیرمجموعه شما ثبت نشده است.")
        return

    await state.set_state(ResponsibleSendCard.choosing_user)
    await state.update_data(responsible_can_direct=current_user.can_approve_directly)

    await message.answer(
        "کاربر موردنظر را انتخاب کنید و شناسه او را ارسال نمایید. برای لغو از دکمه «🔙 بازگشت به منوی اصلی» استفاده کنید.",
        reply_markup=cancel_to_main_keyboard(),
    )

    lines = ["📋 کاربران زیرمجموعه شما:"]
    for user in sorted(members, key=lambda item: item.full_name):
        entry = f"{user.id}: {user.full_name} ({user.phone})"
        if not user.telegram_id:
            entry += " (بدون اتصال تلگرام)"
        lines.append(entry)

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

    await message.answer("لطفاً شناسه کاربر را ارسال کنید.")


@router.message(StateFilter(ResponsibleSendCard.choosing_user))
async def responsible_send_card_choose_user(message: Message, state: FSMContext) -> None:
    raw_text = (message.text or "").strip()
    if not raw_text.isdigit():
        await message.answer("شناسه کاربر باید عددی باشد.")
        return

    services = get_services(message)
    current_user = await get_current_user(message)
    if current_user is None:
        await message.answer("حساب کاربری شما یافت نشد.")
        await state.clear()
        await state.set_state(ResponsibleMenu.idle)
        return

    user_id = int(raw_text)
    target_user = await services.users.get_by_id(user_id)
    if target_user is None or target_user.manager_id != current_user.id:
        await message.answer("کاربر انتخاب‌شده جزو زیرمجموعه شما نیست.")
        return
    if not target_user.telegram_id:
        await message.answer("این کاربر هنوز ربات را فعال نکرده است. کاربر دیگری را انتخاب کنید.")
        return

    await state.update_data(target_user_id=user_id, target_user_name=target_user.full_name)
    await state.set_state(ResponsibleSendCard.choosing_card_type)
    await message.answer(
        f"کاربر {target_user.full_name} انتخاب شد. لطفاً نوع کارت را مشخص کنید.",
        reply_markup=card_type_keyboard(),
    )


@router.callback_query(StateFilter(ResponsibleSendCard.choosing_card_type), F.data.startswith("card_type:"))
async def responsible_send_card_type(callback: CallbackQuery, state: FSMContext) -> None:
    _, raw_type = callback.data.split(":", maxsplit=1)
    card_type = CardType(raw_type)
    await state.update_data(card_type=raw_type)
    await state.set_state(ResponsibleSendCard.choosing_amount)
    await callback.message.edit_text(
        f"نوع کارت {card_type_title(card_type)} انتخاب شد. مبلغ کارت را تعیین کنید:",
        reply_markup=card_amount_keyboard(),
    )
    await callback.answer()


@router.callback_query(StateFilter(ResponsibleSendCard.choosing_amount), F.data.startswith("card_amount:"))
async def responsible_send_card_amount(callback: CallbackQuery, state: FSMContext) -> None:
    _, raw_amount = callback.data.split(":", maxsplit=1)
    if raw_amount == "custom":
        await callback.answer("ارسال با مبلغ دلخواه پشتیبانی نمی‌شود.", show_alert=True)
        return

    data = await state.get_data()
    target_user_id = data.get("target_user_id")
    card_type_raw = data.get("card_type")
    can_direct = data.get("responsible_can_direct", False)
    if target_user_id is None or card_type_raw is None:
        await state.clear()
        await state.set_state(ResponsibleMenu.idle)
        await callback.message.edit_text("اطلاعات عملیات ناقص بود. دوباره تلاش کنید.")
        await callback.message.answer(
            "به منوی اصلی بازگشتید.",
            reply_markup=responsible_main_keyboard(),
        )
        await callback.answer()
        return

    amount = int(raw_amount)
    services = get_services(callback)
    responsible_user = await get_current_user(callback)
    target_user = await services.users.get_by_id(target_user_id)
    if responsible_user is None or target_user is None:
        await state.clear()
        await state.set_state(ResponsibleMenu.idle)
        await callback.message.edit_text("کاربر یا مسئول یافت نشد.")
        await callback.message.answer(
            "به منوی اصلی بازگشتید.",
            reply_markup=responsible_main_keyboard(),
        )
        await callback.answer()
        return

    card_type = CardType(card_type_raw)

    if can_direct:
        await callback.message.edit_text("⏳ در حال ارسال کارت...")
        try:
            card = await services.cards.take_first_available(
                card_type=card_type,
                amount=amount,
                actor_id=responsible_user.id,
            )
        except NoResultFound:
            await callback.message.edit_text(
                f"❌ هیچ کارت {card_type_title(card_type)} با مبلغ {amount:,} دینار در موجودی نیست.")
            await callback.message.answer(
                "مبلغ دیگری را انتخاب کنید:",
                reply_markup=card_amount_keyboard(),
            )
            await callback.answer()
            return

        caption = (
            f"✅ کارت {card_type_title(card.card_type)} به مبلغ {card.amount:,} دینار برای شما ارسال شد.\n"
            f"ارسال کننده: {responsible_user.full_name}"
        )
        sent = await send_card_to_chat(
            callback.message.bot,
            services,
            card,
            target_user.telegram_id,
            caption,
        )
        if not sent:
            await services.cards.restore_card(card.id, actor_id=responsible_user.id)
            await callback.message.edit_text("ارسال کارت با خطا مواجه شد. کمی بعد دوباره تلاش کنید.")
            await callback.answer()
            return

        try:
            request = await services.requests.create_request(
                requester_id=target_user.id,
                responsible_id=responsible_user.id,
                amount=card.amount,
                request_type=RequestType.FIXED,
                status=RequestStatus.PENDING_MANAGER,
                card_type=card.card_type,
            )
            await services.requests.attach_card(
                request_id=request.id,
                card_id=card.id,
                actor_id=responsible_user.id,
            )
            await services.requests.set_status(
                request.id,
                actor_id=responsible_user.id,
                new_status=RequestStatus.APPROVED,
                note="Direct responsible send",
            )
            await services.requests.set_approver(request.id, responsible_user.id)
        except Exception:
            await services.cards.restore_card(card.id, actor_id=responsible_user.id)
            logger.exception("Failed to register direct responsible card send")
            await callback.message.edit_text("ثبت ارسال کارت با خطا مواجه شد. لطفاً دوباره تلاش کنید.")
            await callback.answer()
            return

        await services.cards.mark_sent(card.id, actor_id=responsible_user.id)
        await notify_inventory_threshold(
            callback.message.bot,
            services,
            card.card_type,
            card.amount,
            exclude_user_id=responsible_user.id,
        )
        structured_logger.log_admin_action(
            action="responsible_send_card_direct",
            admin_id=responsible_user.id,
            target_type="user",
            target_user_id=target_user.id,
            card_type=card.card_type.value,
            amount=card.amount,
            card_id=card.id,
        )

        admins = await services.users.list_admins()
        info_message = (
            f"مسئول {responsible_user.full_name} کارت {card_type_title(card.card_type)}"
            f" به مبلغ {card.amount:,} دینار را برای {target_user.full_name} ارسال کرد."
        )
        for admin in admins:
            if not admin.telegram_id:
                continue
            await callback.message.bot.send_message(admin.telegram_id, info_message)

        await state.clear()
        await state.set_state(ResponsibleMenu.idle)
        await callback.message.edit_text("عملیات ارسال کارت تکمیل شد.")
        await callback.message.answer(
            f"✅ کارت {card_type_title(card.card_type)} به مبلغ {card.amount:,} دینار برای {target_user.full_name} ارسال شد.",
            reply_markup=responsible_main_keyboard(),
        )
        await callback.answer()
        return

    # مسئول اجازه ارسال مستقیم ندارد؛ درخواست برای ادمین ثبت شود
    request = await services.requests.create_request(
        requester_id=target_user.id,
        responsible_id=responsible_user.id,
        amount=amount,
        request_type=RequestType.FIXED,
        status=RequestStatus.PENDING_ACCOUNTING,
        card_type=card_type,
    )

    await notify_accounting(callback.message, services, request, target_user.full_name)
    structured_logger.log_admin_action(
        action="responsible_request_card",
        admin_id=responsible_user.id,
        target_type="user",
        target_user_id=target_user.id,
        card_type=card_type.value,
        amount=amount,
        request_id=request.id,
    )
    await callback.message.edit_text(
        f"✅ درخواست شارژ برای {target_user.full_name} با مبلغ {amount:,} دینار ثبت شد و به ادمین ارسال گردید."
    )

    if target_user.telegram_id:
        await callback.message.bot.send_message(
            target_user.telegram_id,
            f"درخواست شارژ {amount:,} دینار توسط مسئول {responsible_user.full_name} ثبت شد و منتظر تایید ادمین است.",
        )

    await callback.message.answer(
        "به منوی اصلی بازگشتید.",
        reply_markup=responsible_main_keyboard(),
    )

    await state.clear()
    await state.set_state(ResponsibleMenu.idle)
    await callback.answer()


@router.message(ResponsibleMenu.idle, F.text == "🔋 درخواست شارژ")
async def responsible_request_charge(message: Message, state: FSMContext) -> None:
    await state.set_state(ChargeRequestFlow.choosing_amount)
    await state.update_data(origin="responsible")
    await message.answer(
        "💰 مبلغ شارژ مورد نظر را انتخاب کنید.",
        reply_markup=cancel_to_main_keyboard(),
    )
    await message.answer(
        "یکی از گزینه‌های مبلغ را انتخاب کنید:",
        reply_markup=charge_amount_keyboard(),
    )


@router.message(
    StateFilter(
        ChargeRequestFlow.choosing_amount,
        ChargeRequestFlow.waiting_for_custom_amount,
        ChargeRequestFlow.confirming,
        ResponsibleSendCard.choosing_user,
        ResponsibleSendCard.choosing_card_type,
        ResponsibleSendCard.choosing_amount,
        ResponsibleMenu.reports_menu,
    ),
    F.text == CANCEL_TEXT,
)
async def responsible_cancel_operation(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ResponsibleMenu.idle)
    await message.answer(
        "عملیات لغو شد. به منوی اصلی بازگشتید.",
        reply_markup=responsible_main_keyboard(),
    )

