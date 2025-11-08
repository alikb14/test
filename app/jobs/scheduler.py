from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from aiogram import Bot
from aiogram.types import FSInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services import ServiceRegistry
from app.keyboards.cards import calculate_tariff


def _previous_month_range(reference: datetime) -> tuple[datetime, datetime]:
    first_of_month = reference.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_prev = first_of_month - timedelta(seconds=1)
    start_prev = end_prev.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start_prev, end_prev


async def send_monthly_reports(
    *,
    bot: Bot,
    services: ServiceRegistry,
    timezone_name: str,
) -> None:
    now = datetime.now(timezone.utc)
    start, end = _previous_month_range(now)
    records = await services.requests.export_consumed_requests(
        start=start,
        end=end,
    )
    if not records:
        return

    tz = ZoneInfo(timezone_name)
    df = pd.DataFrame(records)
    df["updated_at"] = pd.to_datetime(df["updated_at"], utc=True).dt.tz_convert(tz).dt.strftime(
        "%Y-%m-%d %H:%M"
    )
    df["type"] = df["type"].map({"fixed": "مبلغ ثابت", "custom": "مبلغ دلخواه"})
    df["card_type"] = df["card_type"].map({"asia": "آسیا", "athir": "اثیر"})
    # محاسبه تعرفه واقعی
    df["tariff"] = df["amount"].apply(calculate_tariff)
    # اگر approver خالی بود، از responsible استفاده می‌کنیم
    df["approver"] = df["approver"].fillna(df["responsible"])

    reports_dir = services.cards.media_root.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    summary_file = reports_dir / "monthly_summary.xlsx"
    user_file = reports_dir / "monthly_consumption.xlsx"

    detail_df = df.rename(
        columns={
            "id": "شناسه",
            "amount": "مبلغ اسمی",
            "tariff": "تعرفه واقعی",
            "type": "نوع درخواست",
            "updated_at": "تاریخ ارسال",
            "requester": "درخواست‌کننده",
            "responsible": "مسئول",
            "approver": "تایید‌کننده",
            "card_type": "نوع کارت",
        }
    )

    category_df = (
        df.groupby(["card_type", "amount"])
        .agg(
            تعداد=("id", "count"),
            مجموع_اسمی=("amount", "sum"),
            مجموع_تعرفه=("tariff", "sum")
        )
        .reset_index()
        .rename(columns={"card_type": "نوع کارت", "amount": "مبلغ اسمی"})
    )

    user_df = (
        df.groupby("requester")
        .agg(
            تعداد=("id", "count"),
            مجموع_اسمی=("amount", "sum"),
            مجموع_تعرفه=("tariff", "sum")
        )
        .reset_index()
        .rename(columns={"requester": "کاربر"})
    )

    with pd.ExcelWriter(summary_file, engine="openpyxl") as writer:
        detail_df.to_excel(writer, sheet_name="جزئیات", index=False)
        category_df.to_excel(writer, sheet_name="خلاصه دسته‌بندی", index=False)

    user_df.to_excel(user_file, index=False)

    total_amount = int(df["amount"].sum())
    total_tariff = int(df["tariff"].sum())
    total_count = int(len(df))
    await services.requests.record_monthly_report(
        period_start=start,
        period_end=end,
        total_amount=total_amount,
        report_path=str(summary_file),
    )

    admins = await services.users.list_admins()
    summary_text = (
        f"📅 گزارش ماهانه دوره {start.strftime('%Y-%m')}:\n"
        f"📊 تعداد کارت‌های ارسال‌شده: {total_count}\n"
        f"💰 مجموع مبالغ اسمی: {total_amount:,} دینار\n"
        f"💵 مجموع تعرفه واقعی: {total_tariff:,} دینار"
    )

    for admin in admins:
        if not admin.telegram_id:
            continue
        await bot.send_message(admin.telegram_id, summary_text)
        await bot.send_document(
            admin.telegram_id,
            FSInputFile(str(summary_file)),
            caption="📈 گزارش کلی کارت‌های مصرف‌شده",
        )
        await bot.send_document(
            admin.telegram_id,
            FSInputFile(str(user_file)),
            caption="👥 گزارش مصرف کاربران",
        )


def setup_scheduler(
    *,
    bot: Bot,
    services: ServiceRegistry,
    timezone_name: str,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=ZoneInfo(timezone_name))
    scheduler.add_job(
        send_monthly_reports,
        CronTrigger(day=1, hour=8, minute=0),
        kwargs={"bot": bot, "services": services, "timezone_name": timezone_name},
        id="monthly_reports",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler
