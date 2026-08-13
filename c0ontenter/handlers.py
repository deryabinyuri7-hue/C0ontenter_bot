import asyncio

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from c0ontenter.config import Settings
from c0ontenter.generation_runner import run_provider_generation
from c0ontenter.keyboards import aspect_picker, main_menu
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


class CreationFlow(StatesGroup):
    waiting_for_prompt = State()


MENU_IMAGE = "🖼 Создать изображение"
MENU_VIDEO = "🎬 Создать видео"
MENU_PROMPT = "✨ Улучшить промпт"
MENU_BUY = "💳 Купить кредиты"
MENU_BALANCE = "💎 Баланс"
MENU_HISTORY = "🗂 История"
MENU_HELP = "❓ Помощь"


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

    async def prompt_for_generation(message: Message, kind: str) -> None:
        title = "изображения" if kind == "image" else "видео"
        await message.answer(
            f"Отлично! Выберите формат для {title}.\n"
            "После этого я попрошу описать идею — можно писать обычными словами.",
            reply_markup=aspect_picker(kind),
        )

    async def create_generation(
        message: Message, kind: str, aspect_ratio: str, prompt: str
    ) -> None:
        configured_provider = provider()
        if configured_provider is None:
            await message.answer("Сервис генерации пока настраивается. Попробуйте чуть позже.")
            return
        if message.from_user is None:
            return
        async with sessions() as session:
            user = await find_user(session, message.from_user.id)
            if user is None:
                await message.answer("Сначала нажмите /start — так я создам ваш профиль.")
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
                await message.answer(
                    "Похоже, кредитов пока нет. Нажмите «💳 Купить кредиты», "
                    "когда оплата будет подключена."
                )
                return
            generation.aspect_ratio = aspect_ratio
            await session.commit()

        noun = "изображение" if kind == "image" else "видео"
        progress_message = await message.answer(
            f"Создаю {noun} {aspect_ratio}.\n\n▰▱▱▱▱  10%\n"
            "Задача принята, кредит временно зарезервирован.",
        )

        async def on_progress(percent: int) -> None:
            filled = min(5, max(1, (percent + 19) // 20))
            bar = "▰" * filled + "▱" * (5 - filled)
            try:
                await progress_message.edit_text(
                    f"Создаю {noun} {aspect_ratio}.\n\n{bar}  {percent}%\n"
                    "Это может занять несколько минут — я напишу сразу по готовности."
                )
            except Exception:
                pass

        async def on_success(url: str) -> None:
            try:
                await progress_message.edit_text(
                    f"Готово! Ваше {noun} уже можно открыть:\n{url}\n\n"
                    "Хотите ещё вариант? Кнопки всегда рядом с полем ввода."
                )
            except Exception:
                await message.answer(f"Готово! Вот результат:\n{url}")

        async def on_error(text: str) -> None:
            try:
                await progress_message.edit_text(f"Не получилось завершить генерацию.\n\n{text}")
            except Exception:
                await message.answer(text)

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
                on_success=on_success,
                on_error=on_error,
                on_progress=on_progress,
            )
        )

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
            f" Вам уже доступен приветственный кредит: {settings.welcome_credits}."
            if granted
            else ""
        )
        name = message.from_user.first_name or ""
        await message.answer(
            f"Привет, {name}! Я C0ontenter — помогу создать картинку или короткое видео.\n\n"
            f"Баланс: {credits} кредит(ов).{bonus}\n"
            "Кнопки остаются над полем ввода: не нужно возвращаться к этому сообщению.",
            reply_markup=main_menu(),
        )

    @router.message(F.text == MENU_IMAGE)
    async def image_menu(message: Message) -> None:
        await prompt_for_generation(message, "image")

    @router.message(F.text == MENU_VIDEO)
    async def video_menu(message: Message) -> None:
        await prompt_for_generation(message, "video")

    @router.callback_query(F.data.startswith("aspect:"))
    async def choose_aspect(callback: CallbackQuery, state: FSMContext) -> None:
        _, kind, ratio = (callback.data or "").split(":", maxsplit=2)
        await state.set_state(CreationFlow.waiting_for_prompt)
        await state.update_data(kind=kind, aspect_ratio=ratio)
        await callback.answer()
        await callback.message.answer(
            f"Формат {ratio} выбран. Теперь опишите, что создать.\n\n"
            "Например: «утренний туман над Байкалом, вид с высоты, фотореализм».",
        )

    @router.callback_query(F.data == "flow:cancel")
    async def cancel_flow(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await callback.answer("Отменено")
        await callback.message.answer("Ничего не отправляю. Выберите другое действие в меню ниже.")

    @router.message(CreationFlow.waiting_for_prompt, F.text)
    async def receive_prompt(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        await state.clear()
        prompt = (message.text or "").strip()
        if len(prompt) < 3:
            await message.answer("Опишите идею чуть подробнее — хотя бы несколькими словами.")
            return
        await create_generation(message, data["kind"], data["aspect_ratio"], prompt)

    @router.message(F.text == MENU_BALANCE)
    async def show_balance(message: Message) -> None:
        if message.from_user is None:
            return
        async with sessions() as session:
            user = await find_user(session, message.from_user.id)
            credits = await balance(session, user.id) if user else 0
        await message.answer(f"Сейчас у вас {credits} кредит(ов).")

    @router.message(F.text == MENU_HISTORY)
    async def history(message: Message) -> None:
        if message.from_user is None:
            return
        async with sessions() as session:
            user = await find_user(session, message.from_user.id)
            generations = list(
                await session.scalars(
                    select(Generation)
                    .where(Generation.user_id == user.id if user else False)
                    .order_by(Generation.created_at.desc())
                    .limit(5)
                )
            )
        if not generations:
            await message.answer("История пока пустая. Создадим первую работу?")
            return
        lines = ["Последние генерации:"]
        for item in generations:
            icon = {
                "succeeded": "✅",
                "processing": "⏳",
                "reserved": "⏳",
            }.get(item.status.value, "↩️")
            lines.append(f"{icon} {item.kind} {item.aspect_ratio or ''} — {item.status.value}")
        await message.answer("\n".join(lines))

    @router.message(F.text == MENU_HELP)
    async def help_menu(message: Message) -> None:
        await message.answer(
            "Как пользоваться:\n\n"
            "1. Нажмите «Создать изображение» или «Создать видео».\n"
            "2. Выберите формат.\n"
            "3. Напишите идею обычными словами.\n\n"
            "Кредит списывается только при успешном результате; при ошибке я его возвращаю."
        )

    @router.message(F.text == MENU_PROMPT)
    async def improve_prompt(message: Message) -> None:
        await message.answer(
            "Улучшение промптов появится следующим шагом. Пока просто опишите: объект, действие, "
            "стиль, свет и ракурс — этого уже достаточно для хорошего старта."
        )

    @router.message(F.text == MENU_BUY)
    async def buy_credits(message: Message) -> None:
        await message.answer(
            "Покупка через Telegram Stars ещё подключается. Я сообщу, когда она станет доступна."
        )

    @router.message(Command("image"))
    async def image_command(message: Message) -> None:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) != 3:
            await prompt_for_generation(message, "image")
            return
        await create_generation(message, "image", parts[1], parts[2])

    @router.message(Command("video"))
    async def video_command(message: Message) -> None:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) != 3:
            await prompt_for_generation(message, "video")
            return
        await create_generation(message, "video", parts[1], parts[2])

    @router.message(Command("terms"))
    async def terms(message: Message) -> None:
        await message.answer("Условия использования будут опубликованы до включения платежей.")

    @router.message(Command("support"))
    async def support(message: Message) -> None:
        await message.answer("Опишите проблему и приложите скриншот, если он поможет разобраться.")

    @router.message(Command("paysupport"))
    async def pay_support(message: Message) -> None:
        await message.answer("Для вопроса по оплате укажите Telegram ID и идентификатор платежа.")

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
