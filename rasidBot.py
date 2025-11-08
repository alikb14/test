from __future__ import annotations

import asyncio

from app import get_settings
from app.factory import create_bot, create_dispatcher
from app.handlers import router as root_router
from app.logging import setup_logging
from app.jobs.scheduler import setup_scheduler
from app.services import build_services


async def main() -> None:
    settings = get_settings()
    setup_logging(level=settings.log_level)

    bot = create_bot(settings)
    dp = create_dispatcher()
    services = build_services(settings)
    setattr(bot, "services", services)
    dp.workflow_data.update({"services": services})

    scheduler = setup_scheduler(
        bot=bot,
        services=services,
        timezone_name=settings.timezone,
    )
    setattr(bot, "scheduler", scheduler)

    dp.include_router(root_router)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
