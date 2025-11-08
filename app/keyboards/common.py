from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder


def contact_request_keyboard() -> ReplyKeyboardMarkup:
    """Inline button prompting user to share contact."""

    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📱 اشتراک‌گذاری شماره", request_contact=True))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def admin_main_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="💳 کارت‌ها"),
        KeyboardButton(text="👥 کاربرها"),
    )
    builder.row(
        KeyboardButton(text="📊 گزارش ها"),
        KeyboardButton(text="🔋 درخواست شارژ"),
    )
    return builder.as_markup(resize_keyboard=True)


def admin_cards_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="➕ افزودن کارت"),
        KeyboardButton(text="📋 لیست کارت‌ها"),
    )
    builder.row(KeyboardButton(text="🔙 بازگشت به منوی اصلی"))
    return builder.as_markup(resize_keyboard=True)


def admin_users_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="👤 تعریف کاربر جدید"),
        KeyboardButton(text="👥 لیست کاربرها"),
    )
    builder.row(
        KeyboardButton(text="📤 ارسال کارت برای کاربر"),
        KeyboardButton(text="❌ حذف کاربر"),
    )
    builder.row(KeyboardButton(text="🔙 بازگشت به منوی اصلی"))
    return builder.as_markup(resize_keyboard=True)


def responsible_main_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="📊 گزارش ها"),
        KeyboardButton(text="👥 لیست کاربرها"),
    )
    builder.row(
        KeyboardButton(text="🔋 درخواست شارژ"),
        KeyboardButton(text="📤 ارسال کارت برای کاربر"),
    )
    return builder.as_markup(resize_keyboard=True)


def user_main_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="🔋 درخواست شارژ"))
    return builder.as_markup(resize_keyboard=True)


def skip_line_expiry_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="⏭️ رد کردن تاریخ صلاحیت"))
    builder.row(KeyboardButton(text="🔙 بازگشت به منوی اصلی"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)


def cancel_to_main_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard with single button to return to main menu."""

    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="🔙 بازگشت به منوی اصلی"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)


def report_selection_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📊 گزارش کارت‌ها"))
    builder.row(KeyboardButton(text="👥 گزارش مصرف کاربرها"))
    builder.row(KeyboardButton(text="🔙 بازگشت به منوی اصلی"))
    return builder.as_markup(resize_keyboard=True)
