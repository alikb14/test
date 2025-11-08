from __future__ import annotations


def normalize_phone(phone: str) -> str:
    """Normalize phone numbers received from Telegram contact payload."""

    digits = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if not digits.startswith("+"):
        digits = "+{}".format(digits)
    return digits
