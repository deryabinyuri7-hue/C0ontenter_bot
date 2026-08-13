from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Создать изображение", callback_data="generation:image")],
            [InlineKeyboardButton(text="Создать видео", callback_data="generation:video")],
            [InlineKeyboardButton(text="Улучшить промпт", callback_data="generation:prompt")],
            [InlineKeyboardButton(text="Купить кредиты", callback_data="buy_credits")],
            [InlineKeyboardButton(text="Баланс", callback_data="balance")],
            [InlineKeyboardButton(text="История", callback_data="history")],
            [InlineKeyboardButton(text="Помощь", callback_data="help")],
        ]
    )
