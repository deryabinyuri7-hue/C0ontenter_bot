from c0ontenter.keyboards import aspect_picker, main_menu


def test_main_menu_is_persistent_and_covers_primary_actions():
    keyboard = main_menu()
    labels = {button.text for row in keyboard.keyboard for button in row}

    assert keyboard.resize_keyboard is True
    assert "🖼 Создать изображение" in labels
    assert "🎬 Создать видео" in labels
    assert "💎 Баланс" in labels
    assert "🗂 История" in labels


def test_image_and_video_offer_only_supported_aspect_ratios():
    image = {button.text for row in aspect_picker("image").inline_keyboard for button in row}
    video = {button.text for row in aspect_picker("video").inline_keyboard for button in row}

    assert {"1:1", "9:16", "16:9"}.issubset(image)
    assert {"9:16", "16:9"}.issubset(video)
    assert "1:1" not in video
