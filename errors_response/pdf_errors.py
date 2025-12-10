PDF_ERROR_MESSAGES = {
    "pdf_analyze_failed": {
        "tr": "PDF analizi başarısız oldu. Lütfen tekrar deneyin.",
        "en": "PDF analysis failed. Please try again.",
        "es": "El análisis del PDF falló. Por favor, inténtalo de nuevo.",
        "fr": "L'analyse du PDF a échoué. Veuillez réessayer.",
        "pt": "A análise do PDF falhou. Por favor, tente novamente.",
        "ru": "Не удалось выполнить анализ PDF. Пожалуйста, попробуйте еще раз.",
    },
    "pdf_summary_failed": {
        "tr": "PDF özeti alınamadı. Lütfen tekrar deneyin.",
        "en": "PDF summary failed. Please try again.",
        "es": "No se pudo generar el resumen del PDF. Por favor, inténtalo de nuevo.",
        "fr": "Le résumé du PDF a échoué. Veuillez réessayer.",
        "pt": "Não foi possível gerar o resumo do PDF. Por favor, tente novamente.",
        "ru": "Не удалось создать сводку PDF. Пожалуйста, попробуйте еще раз.",
    },
    "pdf_qna_failed": {
        "tr": "PDF soru-cevap işlemi başarısız oldu. Lütfen tekrar deneyin.",
        "en": "PDF Q&A failed. Please try again.",
        "es": "La consulta de preguntas y respuestas del PDF falló. Inténtalo de nuevo.",
        "fr": "La session de questions-réponses sur le PDF a échoué. Veuillez réessayer.",
        "pt": "A sessão de perguntas e respostas do PDF falhou. Por favor, tente novamente.",
        "ru": "Не удалось выполнить вопросы-ответы по PDF. Пожалуйста, попробуйте еще раз.",
    },
    "pdf_extract_failed": {
        "tr": "PDF verileri çıkarılamadı. Lütfen tekrar deneyin.",
        "en": "PDF data extraction failed. Please try again.",
        "es": "La extracción de datos del PDF falló. Por favor, inténtalo de nuevo.",
        "fr": "L'extraction de données du PDF a échoué. Veuillez réessayer.",
        "pt": "A extração de dados do PDF falhou. Por favor, tente novamente.",
        "ru": "Не удалось извлечь данные из PDF. Пожалуйста, попробуйте еще раз.",
    },
    "pdf_compare_failed": {
        "tr": "PDF karşılaştırması başarısız oldu. Lütfen tekrar deneyin.",
        "en": "PDF comparison failed. Please try again.",
        "es": "La comparación de PDFs falló. Por favor, inténtalo de nuevo.",
        "fr": "La comparaison des PDF a échoué. Veuillez réessayer.",
        "pt": "A comparação de PDFs falhou. Por favor, tente novamente.",
        "ru": "Не удалось сравнить PDF. Пожалуйста, попробуйте еще раз.",
    },
    "invalid_file_url": {
        "tr": "Geçerli bir PDF URL'si gerekli.",
        "en": "A valid PDF URL is required.",
        "es": "Se requiere una URL de PDF válida.",
        "fr": "Une URL PDF valide est requise.",
        "pt": "É necessário um URL de PDF válido.",
        "ru": "Требуется действительный URL PDF.",
    },
    "file_download_failed": {
        "tr": "PDF indirilemedi. Lütfen URL'yi kontrol edin.",
        "en": "Failed to download PDF. Please check the URL.",
        "es": "No se pudo descargar el PDF. Por favor, revisa la URL.",
        "fr": "Échec du téléchargement du PDF. Veuillez vérifier l'URL.",
        "pt": "Falha ao baixar o PDF. Verifique a URL.",
        "ru": "Не удалось скачать PDF. Пожалуйста, проверьте URL.",
    },
    "file_too_large": {
        "tr": "Dosya boyutu sınırı aşıldı.",
        "en": "File size limit exceeded.",
        "es": "Se excedió el límite de tamaño de archivo.",
        "fr": "La taille du fichier dépasse la limite.",
        "pt": "Limite de tamanho de arquivo excedido.",
        "ru": "Превышен предел размера файла.",
    },
    "gemini_doc_failed": {
        "tr": "Gemini doküman işlemi başarısız oldu.",
        "en": "Gemini document processing failed.",
        "es": "El procesamiento del documento por Gemini falló.",
        "fr": "Le traitement du document par Gemini a échoué.",
        "pt": "O processamento de documentos pelo Gemini falhou.",
        "ru": "Не удалось обработать документ в Gemini.",
    },
    "no_answer_found": {
        "tr": "Belgede uygun bir yanıt bulunamadı.",
        "en": "No suitable answer found in the document.",
        "es": "No se encontró una respuesta adecuada en el documento.",
        "fr": "Aucune réponse appropriée trouvée dans le document.",
        "pt": "Nenhuma resposta adequada encontrada no documento.",
        "ru": "В документе не найден подходящий ответ.",
    },
    "upload_failed": {
        "tr": "PDF Gemini Files API yüklemesi başarısız.",
        "en": "PDF upload to Gemini Files API failed.",
        "es": "La carga del PDF en Gemini Files API falló.",
        "fr": "Le téléchargement du PDF vers l'API Gemini Files a échoué.",
        "pt": "O upload do PDF para a API Gemini Files falhou.",
        "ru": "Не удалось загрузить PDF в Gemini Files API.",
    },
}


def get_pdf_error_message(key: str, language: str | None) -> str:
    lang = (language or "en").lower()
    if lang not in PDF_ERROR_MESSAGES.get(key, {}):
        lang = "en"
    return PDF_ERROR_MESSAGES.get(key, {}).get(lang, PDF_ERROR_MESSAGES.get(key, {}).get("en", "Error"))


__all__ = ["get_pdf_error_message"]


