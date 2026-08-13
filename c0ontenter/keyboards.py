from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def main_menu() -> ReplyKeyboardMarkup:
    """A persistent menu displayed immediately above the message input."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🖼 Создать изображение"), KeyboardButton(text="🎬 Создать видео")],
            [KeyboardButton(text="✨ Улучшить промпт"), KeyboardButton(text="💳 Купить кредиты")],
            [KeyboardButton(text="💎 Баланс"), KeyboardButton(text="🗂 История")],
            [KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие или напишите запрос…",
    )


def aspect_picker(kind: str) -> InlineKeyboardMarkup:
    ratios = ["1:1", "9:16", "16:9"] if kind == "image" else ["9:16", "16:9"]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=ratio, callback_data=f"aspect:{kind}:{ratio}")]
            for ratio in ratios
        ]
        + [[InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")]]
    )
