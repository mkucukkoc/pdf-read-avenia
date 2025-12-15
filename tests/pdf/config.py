"""
Test configuration for PDF endpoints.

This module provides ready-to-use payload templates for every PDF endpoint.
All values are simple placeholders; update URLs/token before running tests.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

# Base settings
API_BASE_URL: str = "https://avenia.onrender.com"
TEST_BEARER_TOKEN: str = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJkYzM5MzQ0YS01NDBiLTRjNTgtYjI0ZC1hN2Y3YmRmNmNlMzgiLCJzaWQiOiJiNTRkYmFiMS1jOTg2LTQzNTQtYWFlYy1mMzkyOTE4MzY3Y2MiLCJqdGkiOiIxZmU4MGMyNy1iN2E5LTRhODUtODRlMi03MmQ4NTk0NjUyZjciLCJpYXQiOjE3NjU1MzQ5MzcsImV4cCI6MTc2NTU0MjEzNywiaXNzIjoiY2hhdGdidG1pbmkiLCJhdWQiOiJjaGF0Z2J0bWluaS1tb2JpbGUifQ.i9sT2FcG6hXj--87VeS-qHkMCicM3Z5JwxgMutkllnQ"

TEST_USER_ID: str = "dc39344a-540b-4c58-b24d-a7f7bdf6ce38"
TEST_CHAT_ID: str = "1765532546062"

# Common test assets
TEST_PDF_URL_1: str = "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/users%2Fdc39344a-540b-4c58-b24d-a7f7bdf6ce38%2Fuploads%2F1765532549796-file.pdf?alt=media&token=51b1a770-e4eb-431a-8a0b-440b35ab43ae"
TEST_PDF_URL_2: str = "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/users%2Fdc39344a-540b-4c58-b24d-a7f7bdf6ce38%2Fuploads%2F1765400463310-file.pdf?alt=media&token=26b9c7a4-23a4-41b1-a1d1-25e618fa12c4"
TEST_PDF_URL_3: str = TEST_PDF_URL_1

# Language to request from backend (lowercase, matches backend normalize_language)
TEST_LANGUAGE: str = "tr"

# Prompts per endpoint (keep short and realistic)
PDF_ANALYZE_PROMPT: str = "PDF'i analiz et, tonunu ve ana noktaları çıkar."
PDF_SUMMARY_PROMPT: str = "PDF'i madde madde özetler misin?"
PDF_QNA_PROMPT: str = "Yanıt verirken sayfa referansı ekle."
PDF_EXTRACT_PROMPT: str = "Önemli tarihleri ve rakamları çıkar."
PDF_COMPARE_PROMPT: str = "İki PDF arasındaki farkları listele."
PDF_REWRITE_PROMPT: str = "Daha profesyonel ve anlaşılır biçimde yeniden yaz."
PDF_CLASSIFY_PROMPT: str = "Belgenin türünü belirle."
PDF_MULTIANALYZE_PROMPT: str = "Ortak temaları ve riskleri çıkar."
PDF_OCR_EXTRACT_PROMPT: str = "Taranmış sayfaları OCR ile okuyup metni ver."
PDF_LAYOUT_PROMPT: str = "Başlık, paragraf ve tabloların düzenini JSON olarak çıkar."
PDF_DEEPEXTRACT_PROMPT: str = "Fatura alanlarını JSON olarak çıkar (tarih, tutar, vergi)."
PDF_GROUNDED_SEARCH_PROMPT: str = "İddiaları doğrula, güven yoksa belirt."
PDF_TRANSLATE_PROMPT: str = "Belgeyi düzgün ingilizceye çevir."
PDF_STRUCTURE_EXPORT_PROMPT: str = "PDF yapısını headings/paragraphs/tables olarak JSON dök."


# Payload templates
def analyze_payload(chat_id: str = TEST_CHAT_ID) -> Dict[str, Any]:
    return {
        "fileUrl": TEST_PDF_URL_1,
        "chatId": chat_id,
        "language": TEST_LANGUAGE,
        "fileName": "analyze.pdf",
        "prompt": PDF_ANALYZE_PROMPT,
    }


def summary_payload(chat_id: str = TEST_CHAT_ID) -> Dict[str, Any]:
    return {
        "fileUrl": TEST_PDF_URL_1,
        "chatId": chat_id,
        "language": TEST_LANGUAGE,
        "fileName": "summary.pdf",
        "summaryLevel": "detailed",
        "prompt": PDF_SUMMARY_PROMPT,
    }


def qna_payload(chat_id: str = TEST_CHAT_ID) -> Dict[str, Any]:
    return {
        "fileUrl": TEST_PDF_URL_1,
        "chatId": chat_id,
        "language": TEST_LANGUAGE,
        "fileName": "qna.pdf",
        "question": "Belgenin yayın tarihi nedir?",
        "prompt": PDF_QNA_PROMPT,
    }


def extract_payload(chat_id: str = TEST_CHAT_ID) -> Dict[str, Any]:
    return {
        "fileUrl": TEST_PDF_URL_1,
        "chatId": chat_id,
        "language": TEST_LANGUAGE,
        "fileName": "extract.pdf",
        "prompt": PDF_EXTRACT_PROMPT,
    }


def compare_payload(chat_id: str = TEST_CHAT_ID) -> Dict[str, Any]:
    return {
        "file1": TEST_PDF_URL_1,
        "file2": TEST_PDF_URL_2,
        "chatId": chat_id,
        "language": TEST_LANGUAGE,
        "fileName": "compare.pdf",
        "prompt": PDF_COMPARE_PROMPT,
    }


def rewrite_payload(chat_id: str = TEST_CHAT_ID) -> Dict[str, Any]:
    return {
        "fileUrl": TEST_PDF_URL_1,
        "chatId": chat_id,
        "language": TEST_LANGUAGE,
        "fileName": "rewrite.pdf",
        "style": "profesyonel",
        "prompt": PDF_REWRITE_PROMPT,
    }


def classify_payload(chat_id: str = TEST_CHAT_ID) -> Dict[str, Any]:
    return {
        "fileUrl": TEST_PDF_URL_1,
        "chatId": chat_id,
        "language": TEST_LANGUAGE,
        "fileName": "classify.pdf",
        "labels": ["contract", "invoice", "report", "article", "resume"],
        "prompt": PDF_CLASSIFY_PROMPT,
    }


def multianalyze_payload(chat_id: str = TEST_CHAT_ID) -> Dict[str, Any]:
    return {
        "fileUrls": [TEST_PDF_URL_1, TEST_PDF_URL_2],
        "chatId": chat_id,
        "language": TEST_LANGUAGE,
        "prompt": PDF_MULTIANALYZE_PROMPT,
    }


def ocr_extract_payload(chat_id: str = TEST_CHAT_ID) -> Dict[str, Any]:
    return {
        "fileUrl": TEST_PDF_URL_3,
        "chatId": chat_id,
        "language": TEST_LANGUAGE,
        "fileName": "ocr.pdf",
        "prompt": PDF_OCR_EXTRACT_PROMPT,
    }


def layout_payload(chat_id: str = TEST_CHAT_ID) -> Dict[str, Any]:
    return {
        "fileUrl": TEST_PDF_URL_1,
        "chatId": chat_id,
        "language": TEST_LANGUAGE,
        "fileName": "layout.pdf",
        "prompt": PDF_LAYOUT_PROMPT,
    }


def deepextract_payload(chat_id: str = TEST_CHAT_ID) -> Dict[str, Any]:
    return {
        "fileUrl": TEST_PDF_URL_1,
        "chatId": chat_id,
        "language": TEST_LANGUAGE,
        "fileName": "deepextract.pdf",
        "fields": ["invoice_date", "invoice_number", "total_amount", "tax_amount"],
        "prompt": PDF_DEEPEXTRACT_PROMPT,
    }


def grounded_search_payload(chat_id: str = TEST_CHAT_ID) -> Dict[str, Any]:
    return {
        "fileUrl": TEST_PDF_URL_1,
        "chatId": chat_id,
        "language": TEST_LANGUAGE,
        "fileName": "grounded.pdf",
        "question": "Belgedeki tarih bilgileri güncel mi?",
        "prompt": PDF_GROUNDED_SEARCH_PROMPT,
    }


def translate_payload(chat_id: str = TEST_CHAT_ID) -> Dict[str, Any]:
    return {
        "fileUrl": TEST_PDF_URL_1,
        "chatId": chat_id,
        "targetLanguage": "tr",
        "sourceLanguage": "en",
        "fileName": "translate.pdf",
        "prompt": PDF_TRANSLATE_PROMPT,
    }


def structure_export_payload(chat_id: str = TEST_CHAT_ID) -> Dict[str, Any]:
    return {
        "fileUrl": TEST_PDF_URL_1,
        "chatId": chat_id,
        "language": TEST_LANGUAGE,
        "fileName": "structure.pdf",
        "prompt": PDF_STRUCTURE_EXPORT_PROMPT,
    }


# Mapping for convenience if iterating in parametric tests
PAYLOAD_BUILDERS: Dict[str, Any] = {
    "analyze": analyze_payload,
    "summary": summary_payload,
    "qna": qna_payload,
    "extract": extract_payload,
    "compare": compare_payload,
    "rewrite": rewrite_payload,
    "classify": classify_payload,
    "multianalyze": multianalyze_payload,
    "ocr_extract": ocr_extract_payload,
    "layout": layout_payload,
    "deepextract": deepextract_payload,
    "grounded_search": grounded_search_payload,
    "translate": translate_payload,
    "structure_export": structure_export_payload,
}


