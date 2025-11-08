from __future__ import annotations

from aiogram import F, Router

from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.exc import NoResultFound

from app.database import Card, CardType, RequestStatus, RequestType, UserRole
from app.handlers.utils import get_current_user, get_services

from app.keyboards.common import (
    admin_main_keyboard,
    responsible_main_keyboard,
    user_main_keyboard,
)
from app.utils.states import AdminMenu, ChargeRequestFlow, ResponsibleMenu, UserMenu


router = Router(name="charge_flow")


def manager_decision_keyboard(request_id: int, can_approve_directly: bool = False):
    builder = InlineKeyboardBuilder()
    if can_approve_directly:
        builder.button(text="✅ تأیید و ارسال برای ادمین", callback_data=f"req_mgr:approve:{request_id}")
        builder.button(text="🚀 تأیید و ارسال کارت", callback_data=f"req_mgr:send:{request_id}")
        builder.button(text="❌ رد", callback_data=f"req_mgr:reject:{request_id}")
        builder.adjust(1, 1, 1)
    else:
        builder.button(text="✅ تأیید", callback_data=f"req_mgr:approve:{request_id}")
        builder.button(text="❌ رد", callback_data=f"req_mgr:reject:{request_id}")
        builder.adjust(2)
    return builder.as_markup()


def accounting_keyboard(request_id: int, options: list[tuple[CardType, int]]):
    builder = InlineKeyboardBuilder()
    for card_type, count in options:
        title = "آسیا" if card_type is CardType.ASIA else "اثیر"
        builder.button(
            text=f"💳 {title} ({count})",
            callback_data=f"req_acc:card:{request_id}:{card_type.value}",
        )
    builder.button(text="❌ رد درخواست", callback_data=f"req_acc:reject:{request_id}")
    builder.adjust(2)
    return builder.as_markup()


def accounting_simple_keyboard(request_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ تایید", callback_data=f"req_acc:approve:{request_id}")
    builder.button(text="❌ رد درخواست", callback_data=f"req_acc:reject:{request_id}")
    builder.adjust(2)
    return builder.as_markup()


async def _finish_flow(message: Message, state: FSMContext, origin: str, request_id: int) -> None:
    await state.clear()
    state_data = await state.get_data()
    
    # Skip confirmation message if this is an admin's self-request
    is_self_request = origin == "admin" and state_data.get("is_self_request", False)
    
    if origin == "admin":
        await state.set_state(AdminMenu.idle)
        if not is_self_request:  # Only send confirmation if not a self-request
            await message.answer(
                f"✅ درخواست شارژ شما با شماره {request_id} ثبت شد و در انتظار حسابداری است.",
                reply_markup=admin_main_keyboard(),
            )
        else:
            await message.answer(
                "در حال پردازش درخواست...",
                reply_markup=admin_main_keyboard(),
            )
    elif origin == "responsible":
        await state.set_state(ResponsibleMenu.idle)
        await message.answer(
            f"✅ درخواست شارژ شما با شماره {request_id} ثبت شد.",
            reply_markup=responsible_main_keyboard(),
        )
    else:
        await state.set_state(UserMenu.idle)
        await message.answer(
            f"✅ درخواست شما با شماره {request_id} ثبت شد و به مسئول ارجاع شد.",
            reply_markup=user_main_keyboard(),
        )


@router.callback_query(
    StateFilter(ChargeRequestFlow.choosing_amount), F.data.startswith("charge_amount:")
)
async def charge_amount_selected(callback: CallbackQuery, state: FSMContext) -> None:
    _, payload = callback.data.split(":", maxsplit=1)
    if payload == "custom":
        await state.set_state(ChargeRequestFlow.waiting_for_custom_amount)
        await callback.message.edit_text("لطفاً مبلغ مورد نظر را به عدد وارد کنید 📝")
        await callback.answer()
        return

    # Get current state data
    data = await state.get_data()
    origin = data.get("origin", "user")
    
    # Update state with amount and request type
    await state.update_data(
        amount=int(payload), 
        request_type=RequestType.FIXED.value
    )
    
    # If this is an admin request, we already have the card type
    # So we can proceed to process the request
    if origin == "admin":
        await callback.message.edit_text("در حال ثبت درخواست شارژ...")
        await _process_request(callback, state)
    else:
        # For non-admin requests, we need to select card type
        await state.set_state(ChargeRequestFlow.choosing_amount)
        await callback.message.edit_text("در حال ثبت درخواست شارژ...")
        await _process_request(callback, state)
        
    await callback.answer()


@router.message(StateFilter(ChargeRequestFlow.waiting_for_custom_amount))
async def charge_custom_amount(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("⚠️ لطفاً مبلغ را فقط با رقم ارسال کنید.")
        return

    await state.update_data(amount=int(text), request_type=RequestType.CUSTOM.value)
    await message.answer("⏳ در حال ثبت درخواست شارژ...")
    await _process_request(message, state)


async def _process_request(event: Message | CallbackQuery, state: FSMContext) -> None:
    services = get_services(event)
    user = await get_current_user(event)
    if user is None:
        message = event if isinstance(event, Message) else event.message
        await message.answer("❌ کاربر شناسایی نشد. لطفاً مجدداً /start را ارسال کنید.")
        await state.clear()
        return

    data = await state.get_data()
    amount = int(data.get("amount", 0))
    origin = data.get("origin", "user")
    request_type = RequestType(data.get("request_type", RequestType.FIXED.value))
    
    # For admin requests, use the selected card type instead of user's line type
    if origin == "admin" and "card_type" in data:
        card_type = CardType(data["card_type"])
    else:
        card_type = user.line_type if user.line_type else None

    if amount <= 0:
        message = event if isinstance(event, Message) else event.message
        await message.answer("❌ مبلغ نامعتبر است. عملیات لغو شد.")
        await state.clear()
        return

    responsible_id: int | None = None
    status = RequestStatus.PENDING_MANAGER
    if user.role is UserRole.USER:
        responsible_id = user.manager_id
        if responsible_id is None:
            message = event if isinstance(event, Message) else event.message
            await message.answer(
                "⚠️ برای شما مسئول تعریف نشده است. لطفاً با مدیر سیستم تماس بگیرید."
            )
            await state.clear()
            return
    elif user.role is UserRole.RESPONSIBLE:
        responsible_id = user.id
        status = RequestStatus.PENDING_ACCOUNTING
    else:  # admin
        responsible_id = None
        status = RequestStatus.PENDING_ACCOUNTING

    request = await services.requests.create_request(
        requester_id=user.id,
        responsible_id=responsible_id,
        amount=amount,
        request_type=request_type,
        status=status,
        card_type=card_type,
    )

    message = event if isinstance(event, Message) else event.message

    if status is RequestStatus.PENDING_MANAGER and responsible_id:
        responsible = await services.users.get_by_id(responsible_id)
        if responsible and responsible.telegram_id:
            await message.bot.send_message(
                responsible.telegram_id,
                f"درخواست جدید شارژ از {user.full_name} به مبلغ {amount:,} دینار.",
                reply_markup=manager_decision_keyboard(request.id, responsible.can_approve_directly),
            )
        else:
            admins = await services.users.list_admins()
            for admin in admins:
                if admin.telegram_id:
                    await message.bot.send_message(
                        admin.telegram_id,
                        f"برای کاربر {user.full_name} مسئول معتبری در تلگرام یافت نشد. "
                        f"درخواست شماره {request.id} را بررسی کنید.",
                    )

    # If it's an admin's own request, handle it directly without notifying others
    if status is RequestStatus.PENDING_ACCOUNTING:
        is_self_request = user.role is UserRole.ADMIN and request.requester_id == user.id
        
        if is_self_request:
            # For admin's own request, show them the approval options directly
            card_type_text = "آسیا" if request.card_type is CardType.ASIA else "اثیر"
            await message.answer(
                f"درخواست شارژ شما به مبلغ {request.amount:,} دینار برای کارت {card_type_text} ثبت شد.\n"
                "لطفاً تأیید یا رد کنید:",
                reply_markup=accounting_simple_keyboard(request.id)
            )
            # Clear the state and set to admin idle without sending another message
            await state.clear()
            await state.set_state(AdminMenu.idle)
            return  # Exit early to prevent _finish_flow from being called
        else:
            # For normal users or requests from others, notify accounting as before
            await notify_accounting(message, services, request, user.full_name)

    await _finish_flow(message, state, origin, request.id)


async def notify_accounting(message: Message, services, request, requester_name: str) -> None:
    """Notify accounting (admins) about a new charge request or approved transaction"""
    admins = await services.users.list_admins()
    if not admins:
        return

    # Get requester info
    requester = await services.users.get_by_id(request.requester_id)
    
    # Determine the card type from the request if available, otherwise fall back to user's line type
    card_type = request.card_type
    if not card_type and requester and requester.line_type:
        card_type = requester.line_type
    
    # Set the card type text
    card_type_text = "نامشخص"
    if card_type:
        card_type_text = "آسیا" if card_type is CardType.ASIA else "اثیر"

    # Determine if this is a notification or a request for approval
    is_notification = request.status is RequestStatus.APPROVED
    
    text = (
        f"{'✅ ' if is_notification else ''}درخواست شارژ شماره {request.id}\n"
        f"متقاضی: {requester_name}\n"
        f"مبلغ: {request.amount:,} دینار\n"
        f"نوع کارت درخواستی: {card_type_text}"
    )
    
    if is_notification:
        text += "\n\n✅ این درخواست توسط ادمین تأیید و انجام شد."
    else:
        text += "\n\nلطفاً درخواست را تایید یا رد کنید."
    
    # Get the bot instance from the message
    bot = message.bot
    
    # Try to send to all admins except the requester if it's their own request
    for admin in admins:
        if not admin.telegram_id:
            continue
            
        # Skip notifying the requester if it's their own request (they already know)
        if not is_notification and admin.id == request.requester_id:
            continue
            
        try:
            await bot.send_message(
                chat_id=admin.telegram_id,
                text=text,
                reply_markup=None if is_notification else accounting_simple_keyboard(request.id),
            )
        except Exception as e:
            # Log the error but continue with other admins
            import logging
            logging.error(f"Failed to send notification to admin {admin.id}: {str(e)}")
            continue


@router.callback_query(F.data.startswith("req_mgr:"))
async def handle_manager_decision(callback: CallbackQuery, state: FSMContext) -> None:
    _, action, raw_id = callback.data.split(":", maxsplit=2)
    request_id = int(raw_id)
    services = get_services(callback)
    manager = await get_current_user(callback)
    if manager is None:
        await callback.answer("حساب کاربری شما یافت نشد.", show_alert=True)
        return

    request = await services.requests.get_request(request_id)
    if request is None:
        await callback.answer("درخواست یافت نشد.", show_alert=True)
        return

    if request.responsible_id != manager.id:
        await callback.answer("شما مجاز به بررسی این درخواست نیستید.", show_alert=True)
        return

    if request.status is not RequestStatus.PENDING_MANAGER:
        await callback.answer("این درخواست قبلاً بررسی شده است.", show_alert=True)
        return

    requester = await services.users.get_by_id(request.requester_id)
    requester_name = requester.full_name if requester else "نامشخص"
    
    if action == "approve":
        await services.requests.set_status(
            request_id,
            actor_id=manager.id,
            new_status=RequestStatus.PENDING_ACCOUNTING,
        )
        await callback.message.edit_text(
            f"✅ درخواست شماره {request.id} تأیید شد و به حسابداری ارسال گردید."
        )
        await notify_accounting(callback.message, services, request, requester_name)
        if requester and requester.telegram_id:
            await callback.message.bot.send_message(
                requester.telegram_id,
                f"✅ درخواست شارژ شما به مبلغ {request.amount:,} دینار تأیید شد و در انتظار حسابداری است.",
            )
    elif action == "send":
        # مسئول می‌خواهد مستقیماً کارت را ارسال کند
        if not manager.can_approve_directly:
            await callback.answer("شما مجوز ارسال مستقیم کارت را ندارید.", show_alert=True)
            return
        
        # گرفتن گزینه‌های کارت موجود
        options = await _accounting_options(services, request.amount)
        if not options:
            await callback.answer("هیچ کارت مناسبی برای این مبلغ در موجودی نیست.", show_alert=True)
            return
        
        # انتخاب اولین نوع کارت موجود
        card_type, _ = options[0]
        try:
            card = await services.cards.take_first_available(
                card_type=card_type,
                amount=request.amount,
                actor_id=manager.id,
            )
        except NoResultFound:
            await callback.answer("موجودی کارت به اتمام رسیده است.", show_alert=True)
            return
        
        # اتصال کارت به درخواست و ثبت approver
        await services.requests.attach_card(
            request_id,
            card_id=card.id,
            actor_id=manager.id,
        )
        await services.requests.set_approver(request_id, manager.id)
        await services.requests.set_status(
            request_id,
            actor_id=manager.id,
            new_status=RequestStatus.APPROVED,
        )
        
        # بررسی تلگرام کاربر
        if not requester or not requester.telegram_id:
            await callback.answer("کاربر در تلگرام ثبت‌نام نکرده است. نمی‌توان کارت را ارسال کرد.", show_alert=True)
            return
        
        # ارسال کارت به کاربر
        caption = (
            f"✅ درخواست شارژ شما به مبلغ {request.amount:,} دینار تأیید شد.\n"
            "💳 تصویر کارت در پیوست ارسال شده است."
        )
        card_sent = await send_card_to_chat(callback.message.bot, services, card, requester.telegram_id, caption)
        
        if not card_sent:
            await callback.answer("ارسال کارت با خطا مواجه شد. لطفاً دوباره تلاش کنید.", show_alert=True)
            return
        
        await services.cards.mark_sent(card.id, actor_id=manager.id)
        await callback.message.edit_text(
            f"✅ درخواست شماره {request.id} تأیید و کارت برای {requester_name} ارسال شد."
        )
        
        # اطلاع‌رسانی به ادمین‌ها (قبل از چک موجودی تا در صورت خطا اطلاع‌رسانی انجام شده باشد)
        print(f"🔍 DEBUG: شروع اطلاع‌رسانی به ادمین‌ها برای درخواست {request.id}")
        admins = await services.users.list_admins()
        print(f"🔍 DEBUG: تعداد ادمین‌ها: {len(admins)}")
        for admin in admins:
            print(f"🔍 DEBUG: بررسی ادمین {admin.id} (telegram_id: {admin.telegram_id}, manager_id: {manager.id})")
            if admin.telegram_id and admin.id != manager.id:
                try:
                    print(f"✅ DEBUG: در حال ارسال پیام به ادمین {admin.id}")
                    await callback.message.bot.send_message(
                        admin.telegram_id,
                        f"👨‍💼 مسئول {manager.full_name} درخواست شماره {request.id} را تأیید و کارت را برای {requester_name} ارسال کرد.\n"
                        f"💰 مبلغ: {request.amount:,} دینار",
                    )
                    print(f"✅ DEBUG: پیام به ادمین {admin.id} ارسال شد")
                except Exception as e:
                    print(f"❌ DEBUG: خطا در ارسال پیام به ادمین {admin.id}: {e}")
            else:
                print(f"⏭️ DEBUG: ادمین {admin.id} رد شد - telegram_id: {admin.telegram_id}, شرط != manager: {admin.id != manager.id}")
        
        # چک کردن موجودی (بعد از اطلاع‌رسانی)
        try:
            await _check_inventory_threshold(callback, services, card.card_type, card.amount)
        except Exception as e:
            print(f"⚠️ خطا در چک موجودی: {e}")
    elif action == "reject":
        await services.requests.set_status(
            request_id,
            actor_id=manager.id,
            new_status=RequestStatus.REJECTED,
        )
        await callback.message.edit_text(f"درخواست شماره {request.id} رد شد.")
        if requester and requester.telegram_id:
            await callback.message.bot.send_message(
                requester.telegram_id,
                f"❌ درخواست شارژ شما به مبلغ {request.amount:,} دینار توسط مسئول رد شد.",
            )

    await callback.answer()


async def _accounting_options(services, amount: int) -> list[tuple[CardType, int]]:
    options: list[tuple[CardType, int]] = []
    for card_type in CardType:
        count = await services.cards.count_available(card_type, amount)
        if count:
            options.append((card_type, count))
    return options


@router.callback_query(F.data.startswith("req_acc:"))
async def handle_accounting_decision(callback: CallbackQuery, state: FSMContext) -> None:
    _, action, request_id_str, *rest = callback.data.split(":")
    request_id = int(request_id_str)
    services = get_services(callback)
    admin = await get_current_user(callback)
    if admin is None or admin.role is not UserRole.ADMIN:
        await callback.answer("دسترسی لازم را ندارید.", show_alert=True)
        return

    request = await services.requests.get_request(request_id)
    if request is None:
        await callback.answer("درخواست یافت نشد.", show_alert=True)
        return

    if request.status is not RequestStatus.PENDING_ACCOUNTING:
        await callback.answer("این درخواست قبلاً بررسی شده است.", show_alert=True)
        return

    if action == "reject":
        await services.requests.set_status(
            request_id,
            actor_id=admin.id,
            new_status=RequestStatus.REJECTED,
        )
        await callback.message.edit_text(f"❌ درخواست شماره {request.id} توسط شما رد شد.")
        requester = await services.users.get_by_id(request.requester_id)
        
        # Check if this is a self-request by a responsible user
        is_self_request = request.responsible_id and request.responsible_id == request.requester_id
        
        if requester and requester.telegram_id:
            # Always notify the requester
            await callback.message.bot.send_message(
                requester.telegram_id,
                f"❌ درخواست شارژ شما به مبلغ {request.amount:,} دینار توسط حسابداری رد شد.",
            )
        
        # Notify responsible only if it's not a self-request
        if request.responsible_id and not is_self_request:
            responsible = await services.users.get_by_id(request.responsible_id)
            if responsible and responsible.telegram_id:
                requester_name = requester.full_name if requester else "نامشخص"
                await callback.message.bot.send_message(
                    responsible.telegram_id,
                    f"❌ درخواست شماره {request.id} برای {requester_name} توسط حسابداری رد شد.\n"
                    f"💰 مبلغ: {request.amount:,} دینار",
                )
        await callback.answer()
        return

    # تایید: انتخاب خودکار نوع کارت بر اساس نوع خط کاربر
    if action == "approve":
        requester = await services.users.get_by_id(request.requester_id)
        if not requester or not requester.line_type:
            await callback.answer("نوع خط کاربر مشخص نیست. لطفاً ابتدا نوع خط را برای کاربر ثبت کنید.", show_alert=True)
            return
        card_type = requester.line_type
        try:
            card = await services.cards.take_first_available(
                card_type=card_type,
                amount=request.amount,
                actor_id=admin.id,
            )
        except NoResultFound:
            await callback.answer("موجودی کارت مناسب برای این کاربر وجود ندارد.", show_alert=True)
            return

    await services.requests.attach_card(
        request_id,
        card_id=card.id,
        actor_id=admin.id,
    )
    await services.requests.set_approver(request_id, admin.id)
    await services.requests.set_status(
        request_id,
        actor_id=admin.id,
        new_status=RequestStatus.APPROVED,
    )

    requester = await services.users.get_by_id(request.requester_id)
    caption = (
        f"درخواست شارژ شما به مبلغ {request.amount:,} دینار تأیید شد.\n"
        "تصویر کارت در پیوست ارسال شده است."
    )
    if requester and requester.telegram_id:
        await send_card_to_chat(callback.message.bot, services, card, requester.telegram_id, caption)

    await services.cards.mark_sent(card.id, actor_id=admin.id)
    
    # Notify responsible if exists and it's not a self-request
    if request.responsible_id and request.responsible_id != request.requester_id:
        responsible = await services.users.get_by_id(request.responsible_id)
        if responsible and responsible.telegram_id:
            await callback.message.bot.send_message(
                responsible.telegram_id,
                f"درخواست شماره {request.id} برای {requester.full_name if requester else 'کاربر'} تأیید و ارسال شد.",
            )
    
    # If this is an admin's self-request, notify other admins
    if admin.id == request.requester_id:
        admins = await services.users.list_admins()
        for other_admin in admins:
            if other_admin.id != admin.id and other_admin.telegram_id:
                try:
                    await callback.message.bot.send_message(
                        other_admin.telegram_id,
                        f"✅ ادمین {admin.full_name} یک کارت {card.card_type.value} به مبلغ {request.amount:,} دینار دریافت کرد."
                        f"\n🆔 شماره درخواست: {request.id}"
                    )
                except Exception as e:
                    import logging
                    logging.error(f"Failed to notify admin {other_admin.id}: {str(e)}")
    
    await _check_inventory_threshold(callback, services, card.card_type, card.amount)
    await callback.message.edit_text(
        f"کارت {card.card_type.value} برای درخواست شماره {request.id} ارسال شد."
        + ("\n\n✅ سایر ادمین‌ها مطلع شدند." if admin.id == request.requester_id else "")
    )
    await callback.answer("کارت برای کاربر ارسال شد.")


async def send_card_to_chat(bot, services, card: Card, chat_id: int, caption: str) -> bool:
    """ارسال کارت به کاربر. True برمی‌گرداند اگر موفق باشد."""
    caption_with_serial = caption
    if card.serial_number:
        caption_with_serial += f"\n🔢 سریال کارت: {card.serial_number}"

    if card.image_file_id:
        try:
            await bot.send_photo(chat_id, card.image_file_id, caption=caption_with_serial)
            return True
        except TelegramBadRequest:
            pass

    if card.image_path:
        base = services.cards.media_root.parent
        file_path = (base / card.image_path).resolve()
        if file_path.exists():
            try:
                await bot.send_photo(chat_id, FSInputFile(str(file_path)), caption=caption_with_serial)
                return True
            except Exception:
                pass

    # اگر ارسال عکس موفق نشد، پیام متنی ارسال شود
    warning_note = ""
    if not card.serial_number:
        warning_note = "\n⚠️ فایل کارت در دسترس نبود."
    elif card.image_file_id or card.image_path:
        warning_note = "\n⚠️ ارسال تصویر موفق نبود؛ لطفاً از سریال ارائه‌شده استفاده کنید."

    try:
        await bot.send_message(chat_id, caption_with_serial + warning_note)
        return True
    except Exception:
        return False


async def _check_inventory_threshold(callback: CallbackQuery, services, card_type: CardType, amount: int) -> None:
    remaining = await services.cards.count_available(card_type, amount)
    if remaining > 2:
        return

    admins = await services.users.list_admins()
    title = "آسیا" if card_type is CardType.ASIA else "اثیر"
    for admin in admins:
        if not admin.telegram_id:
            continue
        await callback.message.bot.send_message(
            admin.telegram_id,
            f"موجودی کارت {title} با مبلغ {amount:,} دینار به {remaining} عدد رسیده است. لطفاً شارژ را تکمیل کنید.",
        )
