from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AuthState(StatesGroup):
    waiting_for_contact = State()


class AdminMenu(StatesGroup):
    idle = State()
    cards_menu = State()
    users_menu = State()
    reports_menu = State()


class ResponsibleMenu(StatesGroup):
    idle = State()
    reports_menu = State()


class UserMenu(StatesGroup):
    idle = State()


class AdminAddCard(StatesGroup):
    choosing_type = State()
    choosing_amount = State()
    waiting_for_image = State()
    confirming = State()


class AdminDefineUser(StatesGroup):
    waiting_for_phone = State()
    waiting_for_line_expiry = State()
    waiting_for_full_name = State()
    choosing_role = State()
    choosing_approval_permission = State()
    choosing_department = State()
    choosing_manager = State()
    choosing_line_type = State()


class AdminDeleteUser(StatesGroup):
    choosing_user = State()
    confirming = State()


class AdminSendCard(StatesGroup):
    choosing_user = State()
    choosing_card_type = State()
    choosing_amount = State()


class ResponsibleSendCard(StatesGroup):
    choosing_user = State()
    choosing_card_type = State()
    choosing_amount = State()


class ChargeRequestFlow(StatesGroup):
    choosing_amount = State()
    waiting_for_custom_amount = State()
    choosing_card_type = State()  # New state for admin card type selection
    confirming = State()
