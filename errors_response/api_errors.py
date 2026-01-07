API_ERROR_MESSAGES = {
    "upstream_500": {
        "tr": "Beklenmeyen bir sorun oluştu. Lütfen tekrar deneyin.",
        "en": "Something went wrong. Please try again.",
        "es": "Ocurrió un problema inesperado. Inténtalo de nuevo.",
        "fr": "Un problème inattendu est survenu. Veuillez réessayer.",
        "pt": "Ocorreu um problema inesperado. Tente novamente.",
        "ru": "Произошла непредвиденная ошибка. Попробуйте ещё раз.",
    },
    "upstream_404": {
        "tr": "Üzgünüz, bu özellik şu an kullanılamıyor. Lütfen daha sonra tekrar dene.",
        "en": "Sorry, this feature isn’t available right now. Please try again later.",
        "es": "Lo sentimos, esta función no está disponible ahora. Por favor, inténtalo más tarde.",
        "fr": "Désolé, cette fonctionnalité n’est pas disponible pour le moment. Réessayez plus tard.",
        "pt": "Desculpe, este recurso não está disponível agora. Tente novamente mais tarde.",
        "ru": "Извините, эта функция сейчас недоступна. Пожалуйста, попробуйте позже.",
    },
    "upstream_401": {
        "tr": "Şu an isteğin tamamlanamadı. Lütfen biraz sonra tekrar dene.",
        "en": "We couldn’t complete this request. Please try again soon.",
        "es": "No pudimos completar esta solicitud. Inténtalo de nuevo en breve.",
        "fr": "Impossible de terminer la requête. Réessayez dans un instant.",
        "pt": "Não conseguimos concluir este pedido. Tente novamente em breve.",
        "ru": "Не удалось выполнить запрос. Попробуйте чуть позже.",
    },
    "upstream_403": {
        "tr": "Şu an isteğin tamamlanamadı. Lütfen biraz sonra tekrar dene.",
        "en": "We couldn’t complete this request. Please try again soon.",
        "es": "No pudimos completar esta solicitud. Inténtalo de nuevo en breve.",
        "fr": "Impossible de terminer la requête. Réessayez dans un instant.",
        "pt": "Não conseguimos concluir este pedido. Tente novamente em breve.",
        "ru": "Не удалось выполнить запрос. Попробуйте чуть позже.",
    },
    "upstream_429": {
        "tr": "Çok fazla istek gönderildi. Lütfen biraz bekleyip tekrar deneyin.",
        "en": "Too many requests. Please wait a moment and try again.",
        "es": "Demasiadas solicitudes. Por favor espera un momento y vuelve a intentarlo.",
        "fr": "Trop de requêtes. Veuillez patienter un instant puis réessayer.",
        "pt": "Muitas solicitações. Aguarde um momento e tente novamente.",
        "ru": "Слишком много запросов. Подождите немного и попробуйте снова.",
    },
    "upstream_timeout": {
        "tr": "Bağlantı çok yavaş. Lütfen internetini kontrol edip tekrar dene.",
        "en": "The connection is slow. Please check your internet and try again.",
        "es": "La conexión está lenta. Revisa tu internet y vuelve a intentarlo.",
        "fr": "La connexion est lente. Vérifiez votre internet et réessayez.",
        "pt": "A conexão está lenta. Verifique sua internet e tente novamente.",
        "ru": "Соединение медленное. Проверьте интернет и попробуйте снова.",
    },
    "bad_json_from_upstream": {
        "tr": "Bilgiler yüklenirken bir sorun oluştu. Lütfen tekrar dene.",
        "en": "There was an issue loading the data. Please try again.",
        "es": "Hubo un problema al cargar los datos. Inténtalo de nuevo.",
        "fr": "Un problème est survenu lors du chargement des données. Veuillez réessayer.",
        "pt": "Ocorreu um problema ao carregar os dados. Tente novamente.",
        "ru": "Произошла ошибка при загрузке данных. Попробуйте ещё раз.",
    },
    "invalid_request": {
        "tr": "Gönderilen istek geçersiz. Lütfen alanları kontrol edin.",
        "en": "The request is invalid. Please check the fields.",
        "es": "La solicitud es inválida. Por favor revisa los campos.",
        "fr": "La requête est invalide. Veuillez vérifier les champs.",
        "pt": "A solicitação é inválida. Verifique os campos.",
        "ru": "Некорректный запрос. Пожалуйста, проверьте поля.",
    },
    "file_too_large": {
        "tr": "Dosya boyutu sınırı aşıldı.",
        "en": "File size limit exceeded.",
        "es": "Se excedió el límite de tamaño de archivo.",
        "fr": "La taille du fichier dépasse la limite.",
        "pt": "O limite de tamanho de arquivo foi excedido.",
        "ru": "Превышен предел размера файла.",
    },
    "file_download_failed": {
        "tr": "Beklenmeyen bir hata oluştu. Lütfen sonra tekrar deneyin.",
        "en": "An unexpected error occurred. Please try again later.",
        "es": "Ocurrió un error inesperado. Inténtalo de nuevo más tarde.",
        "fr": "Une erreur inattendue s'est produite. Veuillez réessayer plus tard.",
        "pt": "Ocorreu um erro inesperado. Tente novamente mais tarde.",
        "ru": "Произошла непредвиденная ошибка. Попробуйте позже.",
    },
    "unknown_error": {
        "tr": "Beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.",
        "en": "An unexpected error occurred. Please try again.",
        "es": "Ocurrió un error inesperado. Por favor, inténtalo de nuevo.",
        "fr": "Une erreur inattendue s'est produite. Veuillez réessayer.",
        "pt": "Ocorreu um erro inesperado. Por favor, tente novamente.",
        "ru": "Произошла непредвиденная ошибка. Пожалуйста, попробуйте снова.",
    },
}


def get_api_error_message(key: str, language: str | None) -> str:
    lang = (language or "en").lower()
    if lang not in API_ERROR_MESSAGES.get(key, {}):
        lang = "en"
    return API_ERROR_MESSAGES.get(key, {}).get(lang, API_ERROR_MESSAGES.get(key, {}).get("en", "Error"))


__all__ = ["get_api_error_message", "API_ERROR_MESSAGES"]

