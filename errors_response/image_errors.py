MESSAGES_NO_IMAGE_GENERATE = {
    "tr": "Şu an bağlantı zayıf görünüyor, lütfen biraz sonra tekrar deneyin. Görsel oluşturulamadı.",
    "en": "The connection seems weak right now, please try again shortly. The image could not be generated.",
    "es": "La conexión parece débil en este momento, inténtalo de nuevo más tarde. No se pudo generar la imagen.",
    "fr": "La connexion semble faible pour le moment, réessayez un peu plus tard. L’image n’a pas pu être générée.",
    "pt": "A conexão parece fraca no momento, tente novamente em breve. Não foi possível gerar a imagem.",
    "ru": "Соединение сейчас нестабильно, попробуйте позже. Не удалось создать изображение.",
}

MESSAGES_IMAGE_EDIT_FAILED = {
    "tr": "Şu an bağlantı zayıf görünüyor, lütfen biraz sonra tekrar deneyin. Görsel düzenlenemedi.",
    "en": "The connection seems weak right now, please try again shortly. The image could not be edited.",
    "es": "La conexión parece débil en este momento, inténtalo de nuevo más tarde. No se pudo editar la imagen.",
    "fr": "La connexion semble faible pour le moment, réessayez un peu plus tard. L’image n’a pas pu être modifiée.",
    "pt": "A conexão parece fraca no momento, tente novamente em breve. Não foi possível editar a imagem.",
    "ru": "Соединение сейчас нестабильно, попробуйте позже. Не удалось отредактировать изображение.",
}


def get_no_image_generate_message(language: str | None) -> str:
    if not language:
        return MESSAGES_NO_IMAGE_GENERATE["en"]
    key = (language or "").lower()[:2]
    return MESSAGES_NO_IMAGE_GENERATE.get(key, MESSAGES_NO_IMAGE_GENERATE["en"])


def get_image_edit_failed_message(language: str | None) -> str:
    if not language:
        return MESSAGES_IMAGE_EDIT_FAILED["en"]
    key = (language or "").lower()[:2]
    return MESSAGES_IMAGE_EDIT_FAILED.get(key, MESSAGES_IMAGE_EDIT_FAILED["en"])


__all__ = ["get_no_image_generate_message", "get_image_edit_failed_message"]

