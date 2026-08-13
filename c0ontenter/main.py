import asyncio

import structlog
from aiogram import Bot, Dispatcher

from c0ontenter.config import get_settings
from c0ontenter.db import create_session_factory
from c0ontenter.handlers import build_router
from c0ontenter.logging import configure_logging


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = structlog.get_logger(__name__)
    bot = Bot(settings.bot_token.get_secret_value())
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(settings, create_session_factory(settings.database_url)))
    logger.info("bot_starting", mode="long_polling")
    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run())
