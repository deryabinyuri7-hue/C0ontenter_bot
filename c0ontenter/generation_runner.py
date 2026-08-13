import asyncio
from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from c0ontenter.models import Generation, GenerationStatus
from c0ontenter.providers.base import GenerationProvider
from c0ontenter.services import (
    claim_provider_submission,
    set_generation_result,
    set_provider_task,
    settle_generation,
)

logger = structlog.get_logger(__name__)


async def run_provider_generation(
    *,
    sessions: async_sessionmaker[AsyncSession],
    provider: GenerationProvider,
    generation_id: int,
    kind: str,
    prompt: str,
    aspect_ratio: str,
    poll_interval_seconds: int,
    max_wait_seconds: int,
    on_success: Callable[[str], Awaitable[None]],
    on_error: Callable[[str], Awaitable[None]],
    allow_submission: bool = True,
) -> None:
    """Submit once, then poll an existing provider task until it settles."""
    try:
        async with sessions() as session:
            generation = await session.scalar(
                select(Generation).where(Generation.id == generation_id)
            )
            if generation is None:
                return
            task_id = generation.provider_task_id

        if task_id is None:
            if not allow_submission:
                return
            async with sessions() as session:
                if not await claim_provider_submission(session, generation_id):
                    return
            task_id = (
                await provider.create_image_task(prompt=prompt, aspect_ratio=aspect_ratio)
                if kind == "image"
                else await provider.create_video_task(prompt=prompt, aspect_ratio=aspect_ratio)
            )
            async with sessions() as session:
                await set_provider_task(session, generation_id, task_id)

        elapsed = 0
        while elapsed < max_wait_seconds:
            task = await provider.get_task_status(kind=kind, task_id=task_id)
            if task.state == "success" and task.result_url:
                async with sessions() as session:
                    await set_generation_result(session, generation_id, task.result_url)
                    await settle_generation(session, generation_id, success=True)
                await on_success(task.result_url)
                return
            if task.state == "fail":
                raise RuntimeError(task.error_message or "KIE generation failed")
            await asyncio.sleep(poll_interval_seconds)
            elapsed += poll_interval_seconds
        async with sessions() as session:
            await settle_generation(
                session,
                generation_id,
                success=False,
                error_code="provider_timeout",
                timed_out=True,
            )
        await on_error("Время ожидания генерации истекло; кредит возвращён.")
    except Exception as exc:
        logger.warning(
            "provider_generation_failed",
            generation_id=generation_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        async with sessions() as session:
            await settle_generation(
                session, generation_id, success=False, error_code="provider_error"
            )
        await on_error("Генерация не удалась; кредит возвращён.")


async def recover_provider_generations(
    *,
    sessions: async_sessionmaker[AsyncSession],
    provider: GenerationProvider,
    poll_interval_seconds: int,
    max_wait_seconds: int,
) -> None:
    """Resume known provider tasks after a restart without submitting another task."""
    async with sessions() as session:
        generations = list(
            await session.scalars(
                select(Generation).where(
                    Generation.status.in_([GenerationStatus.reserved, GenerationStatus.processing])
                )
            )
        )
    for generation in generations:
        if generation.provider_task_id is None:
            async with sessions() as session:
                await settle_generation(
                    session,
                    generation.id,
                    success=False,
                    error_code="provider_submission_interrupted",
                )
            continue
        await run_provider_generation(
            sessions=sessions,
            provider=provider,
            generation_id=generation.id,
            kind=generation.kind,
            prompt=generation.prompt or "",
            aspect_ratio=generation.aspect_ratio or "",
            poll_interval_seconds=poll_interval_seconds,
            max_wait_seconds=max_wait_seconds,
            on_success=_ignore_success,
            on_error=_ignore_error,
            allow_submission=False,
        )


async def _ignore_success(_: str) -> None:
    return None


async def _ignore_error(_: str) -> None:
    return None
