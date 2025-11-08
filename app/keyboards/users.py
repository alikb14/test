from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

from app.database import User
from app.database import CardType


def user_role_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 کاربر عادی", callback_data="user_role:user")
    builder.button(text="👨‍💼 مسئول", callback_data="user_role:responsible")
    builder.adjust(2)
    return builder.as_markup()


def department_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🌐 شبکه", callback_data="department:network")
    builder.button(text="🏢 مؤسسه", callback_data="department:institute")
    builder.adjust(2)
    return builder.as_markup()


def managers_keyboard(responsibles: list[User]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for responsible in responsibles:
        builder.button(
            text=f"👨‍💼 {responsible.full_name}",
            callback_data=f"manager:{responsible.id}",
        )
    builder.adjust(1)
    return builder.as_markup()


def line_type_keyboard() -> InlineKeyboardMarkup:
    """کیبورد انتخاب نوع خط کاربر"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📱 آسیا", callback_data="line_type:asia")
    builder.button(text="📱 اثیر", callback_data="line_type:athir")
    builder.adjust(2)
    return builder.as_markup()


def approval_permission_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ بله، مجوز ارسال مستقیم دارد", callback_data="approval_permission:yes")
    builder.button(text="❌ خیر، نیاز به تایید ادمین دارد", callback_data="approval_permission:no")
    builder.adjust(1)
    return builder.as_markup()
