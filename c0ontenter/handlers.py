import asyncio

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from c0ontenter.config import Settings
from c0ontenter.generation_runner import run_provider_generation
from c0ontenter.keyboards import main_menu
from c0ontenter.models import Generation, User
from c0ontenter.providers.kie import KieGenerationProvider
from c0ontenter.services import (
    InsufficientCreditsError,
    admin_stats,
    balance,
    grant_manual_credits,
    register_user,
    reserve_generation,
)


def build_router(settings: Settings, sessions: async_sessionmaker[AsyncSession]) -> Router:
    router = Router(name="c0ontenter")

    async def find_user(session: AsyncSession, telegram_id: int) -> User | None:
        return await session.scalar(select(User).where(User.telegram_id == telegram_id))

    def provider() -> KieGenerationProvider | None:
        if not all([settings.kie_api_key, settings.image_model_id]):
            return None
        return KieGenerationProvider(
            api_key=settings.kie_api_key.get_secret_value(),
            image_model_id=settings.image_model_id,
            image_status_path=settings.kie_image_task_status_path,
        )

    async def create_generation(
        message: Message, kind: str, aspect_ratio: str, prompt: str
    ) -> None:
        configured_provider = provider()
        if configured_provider is None:
            await message.answer("KIE ещё не настроен. Обратитесь к администратору.")
            return
        if message.from_user is None:
            return
        if kind == "image" and aspect_ratio not in {"1:1", "9:16", "16:9"}:
            await message.answer("Для изображения выберите: 1:1, 9:16 или 16:9.")
            return
        if kind == "video" and aspect_ratio not in {"9:16", "16:9"}:
            await message.answer("Для видео выберите: 9:16 или 16:9.")
            return
        async with sessions() as session:
            user = await find_user(session, message.from_user.id)
            if user is None:
                await message.answer("Сначала отправьте /start.")
                return
            try:
                generation = await reserve_generation(
                    session,
                    user_id=user.id,
                    idempotency_key=f"tg:{message.from_user.id}:{message.message_id}:{kind}",
                    kind=kind,
                    prompt=prompt,
                    cost=1,
                )
            except InsufficientCreditsError:
                await message.answer("Недостаточно кредитов.")
                return
            generation.aspect_ratio = aspect_ratio
            await session.commit()
        await message.answer(
            "Задача принята. Кредит зарезервирован; сообщу, когда результат будет готов."
        )
        asyncio.create_task(
            run_provider_generation(
                sessions=sessions,
                provider=configured_provider,
                generation_id=generation.id,
                kind=kind,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                poll_interval_seconds=settings.kie_poll_interval_seconds,
                max_wait_seconds=settings.kie_max_wait_seconds,
                on_success=lambda url: message.answer(f"Готово: {url}"),
                on_error=message.answer,
            )
        )

    @router.message(Command("image"))
    async def image_command(message: Message) -> None:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) != 3:
            await message.answer("Использование: /image <1:1|9:16|16:9> <промпт>")
            return
        await create_generation(message, "image", parts[1], parts[2])

    @router.message(Command("video"))
    async def video_command(message: Message) -> None:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) != 3:
            await message.answer("Использование: /video <9:16|16:9> <промпт>")
            return
        await create_generation(message, "video", parts[1], parts[2])

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        if message.from_user is None:
            return
        async with sessions() as session:
            user, granted = await register_user(
                session,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                language_code=message.from_user.language_code,
                welcome_credits=settings.welcome_credits,
            )
            credits = await balance(session, user.id)
        bonus = (
            f" Вам начислен приветственный кредит: {settings.welcome_credits}." if granted else ""
        )
        await message.answer(
            f"Добро пожаловать в C0ontenter! Баланс: {credits}.{bonus}", reply_markup=main_menu()
        )

    @router.message(Command("terms"))
    async def terms(message: Message) -> None:
        await message.answer("Условия использования будут опубликованы до подключения платежей.")

    @router.message(Command("support"))
    async def support(message: Message) -> None:
        await message.answer("Опишите проблему и приложите скриншот, если он есть.")

    @router.message(Command("paysupport"))
    async def pay_support(message: Message) -> None:
        await message.answer("Для вопросов об оплате укажите Telegram ID и идентификатор платежа.")

    @router.callback_query(F.data == "balance")
    async def show_balance(callback: CallbackQuery) -> None:
        async with sessions() as session:
            user = await find_user(session, callback.from_user.id)
            credits = await balance(session, user.id) if user else 0
        await callback.answer(f"Баланс: {credits} кредит(ов)", show_alert=True)

    @router.callback_query(F.data == "history")
    async def history(callback: CallbackQuery) -> None:
        async with sessions() as session:
            user = await find_user(session, callback.from_user.id)
            count = (
                await session.scalar(
                    select(func.count(Generation.id)).where(Generation.user_id == user.id)
                )
                if user
                else 0
            )
        await callback.answer(f"Генераций в истории: {count or 0}", show_alert=True)

    @router.callback_query(F.data.in_({"buy_credits", "help"}))
    async def pending_feature(callback: CallbackQuery) -> None:
        messages = {
            "buy_credits": "Покупка кредитов будет добавлена на следующем этапе.",
            "help": "Выберите действие из меню. Доступны /terms, /support и /paysupport.",
        }
        await callback.answer()
        await callback.message.answer(messages[callback.data])

    @router.callback_query(F.data.startswith("generation:"))
    async def generation_pending(callback: CallbackQuery) -> None:
        await callback.answer()
        kind = callback.data.split(":", maxsplit=1)[1]
        command = (
            "/image <1:1|9:16|16:9> <промпт>"
            if kind == "image"
            else "/video <9:16|16:9> <промпт>"
        )
        await callback.message.answer(f"Введите команду: {command}")

    def is_admin(message: Message) -> bool:
        return bool(message.from_user and message.from_user.id in settings.admin_ids)

    @router.message(Command("admin_stats"))
    async def show_admin_stats(message: Message) -> None:
        if not is_admin(message):
            return
        async with sessions() as session:
            stats = await admin_stats(session)
        await message.answer(
            f"Пользователи: {stats['users']}\nПлатящие: {stats['paying_users']}\n"
            f"Генерации: {stats['generations']}\nОшибки: {stats['errors']}"
        )

    @router.message(Command("grant"))
    async def grant(message: Message) -> None:
        if not is_admin(message):
            return
        parts = (message.text or "").split()
        if len(parts) != 3:
            await message.answer("Использование: /grant <telegram_id> <credits>")
            return
        try:
            telegram_id, credits = int(parts[1]), int(parts[2])
            async with sessions() as session:
                total = await grant_manual_credits(
                    session,
                    telegram_id=telegram_id,
                    credits=credits,
                    note=f"manual grant by {message.from_user.id}",
                )
        except ValueError as exc:
            await message.answer(f"Не удалось начислить кредиты: {exc}")
            return
        await message.answer(f"Начислено {credits}. Новый баланс: {total}.")

    return router
