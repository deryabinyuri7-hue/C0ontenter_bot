import asyncio

import structlog
from aiogram import Bot, Dispatcher

from c0ontenter.config import get_settings
from c0ontenter.db import create_session_factory
from c0ontenter.generation_runner import recover_provider_generations
from c0ontenter.handlers import build_router
from c0ontenter.logging import configure_logging
from c0ontenter.providers.kie import KieGenerationProvider


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = structlog.get_logger(__name__)
    bot = Bot(settings.bot_token.get_secret_value())
    dispatcher = Dispatcher()
    sessions = create_session_factory(settings.database_url)
    dispatcher.include_router(build_router(settings, sessions))
    if all([settings.kie_api_key, settings.image_model_id]):
        provider = KieGenerationProvider(
            api_key=settings.kie_api_key.get_secret_value(),
            image_model_id=settings.image_model_id,
            image_status_path=settings.kie_image_task_status_path,
        )
        asyncio.create_task(
            recover_provider_generations(
                sessions=sessions,
                provider=provider,
                poll_interval_seconds=settings.kie_poll_interval_seconds,
                max_wait_seconds=settings.kie_max_wait_seconds,
            )
        )
    logger.info("bot_starting", mode="long_polling")
    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run())
