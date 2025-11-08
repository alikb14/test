from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from app.middleware.logging_middleware import LoggingMiddleware

from .config import Settings


def create_bot(settings: Settings) -> Bot:
    """Instantiate Telegram Bot with sensible defaults."""

    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    """Create a dispatcher instance with Redis storage if available, otherwise use MemoryStorage."""
    # Try to use Redis if available, otherwise fall back to MemoryStorage
    try:
        from redis.asyncio import Redis
        from aiogram.fsm.storage.redis import RedisStorage

        redis = Redis.from_url("redis://localhost:6379/0")
        storage = RedisStorage(redis=redis)
    except (ImportError, ConnectionError):
        storage = MemoryStorage()
    
    # Create dispatcher with logging middleware
    dp = Dispatcher(storage=storage)

    # Register logging middleware for messages and callback queries so events are captured
    logging_middleware = LoggingMiddleware()
    dp.message.middleware.register(logging_middleware)
    dp.callback_query.middleware.register(logging_middleware)

    return dp


async def shutdown(bot: Bot) -> None:
    """Graceful bot shutdown hook."""

    await bot.session.close()
    await asyncio.sleep(0)
