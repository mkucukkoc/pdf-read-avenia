from __future__ import annotations

from typing import Any, Dict, List, Optional

# Lightweight agent definitions mirroring frontend agentFunctions.ts.
# No runtime behavior; use these for server-side routing/tool schemas if needed.

AgentDef = Dict[str, Any]


def get_agent_definitions() -> List[AgentDef]:
    return AGENTS


def get_agent_by_name(name: str) -> Optional[AgentDef]:
    return next((a for a in AGENTS if a.get("name") == name), None)


AGENTS: List[AgentDef] = [
    {
        "name": "chat_agent",
        "description": "Varsayılan sohbet yanıtı (Gemini text).",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "chatId": {"type": "string"},
                "language": {"type": "string"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "weather",
        "description": "Hava durumu bilgisi verir.",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "Şehir veya konum"},
            },
            "required": ["location"],
        },
    },
    {
        "name": "docx",
        "description": "DOCX belge üretir.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "chatId": {"type": "string"},
                "language": {"type": "string"},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "generate_excel",
        "description": "Excel dosyası üretir.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "chatId": {"type": "string"},
                "language": {"type": "string"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "ppt",
        "description": "Sunum (PPT) üretir.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "chatId": {"type": "string"},
                "language": {"type": "string"},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "generate_image_gemini",
        "description": "Gemini ile görsel üretir (backend: /api/v1/image/gemini).",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Görsel açıklaması"},
                "chatId": {"type": "string"},
                "fileName": {"type": "string"},
                "language": {"type": "string"},
                "useGoogleSearch": {
                    "type": "boolean",
                    "description": "Google arama temellendirmesi (varsayılan false).",
                },
                "aspectRatio": {"type": "string"},
            },
            "required": ["prompt", "chatId"],
        },
    },
    {
        "name": "generate_image_gemini_search",
        "description": "Gemini + Google Search ile görsel üretir (backend: /api/v1/image/gemini-search).",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "chatId": {"type": "string"},
                "fileName": {"type": "string"},
                "language": {"type": "string"},
                "aspectRatio": {"type": "string"},
            },
            "required": ["prompt", "chatId"],
        },
    },
    {
        "name": "image_edit_gemini",
        "description": "Gemini ile görsel düzenler (backend: /api/v1/image/gemini-edit).",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "imageUrl": {"type": "string"},
                "chatId": {"type": "string"},
                "language": {"type": "string"},
                "fileName": {"type": "string"},
            },
            "required": ["prompt", "imageUrl", "chatId"],
        },
    },
    {
        "name": "generate_video_gemini",
        "description": "Gemini/Veo ile video üretir (backend: /api/v1/video/gemini).",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "chatId": {"type": "string"},
                "language": {"type": "string"},
                "fileName": {"type": "string"},
                "duration": {"type": "integer"},
                "resolution": {"type": "string"},
            },
            "required": ["prompt", "chatId"],
        },
    },
    {
        "name": "detect_ai_image",
        "description": "Görsel URL'ini analiz eder; gerekirse AI tespit eder.",
        "parameters": {
            "type": "object",
            "properties": {
                "imageFileUrl": {"type": "string"},
                "chatId": {"type": "string"},
                "checkAi": {"type": "boolean"},
            },
            "required": ["imageFileUrl"],
        },
    },
    {
        "name": "detect_ai_video",
        "description": "Video URL'ini analiz eder; AI tespiti yapar.",
        "parameters": {
            "type": "object",
            "properties": {
                "videoFileUrl": {"type": "string"},
                "chatId": {"type": "string"},
            },
            "required": ["videoFileUrl"],
        },
    },
    {
        "name": "detect_ai_document",
        "description": "Doküman URL'ini analiz eder; AI tespiti yapar.",
        "parameters": {
            "type": "object",
            "properties": {
                "fileUrl": {"type": "string"},
                "chatId": {"type": "string"},
            },
            "required": ["fileUrl"],
        },
    },
    {
        "name": "summarize_file_flow",
        "description": "Ekli dosyayı özetler/analiz eder.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "chatId": {"type": "string"},
                "fileName": {"type": "string"},
                "fileMimeType": {"type": "string"},
                "fileSizeMb": {"type": "number"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "ask_with_embeddings",
        "description": "Vektör arama ile soru yanıtlama.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "chatId": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "convert_pdf_to_word",
        "description": "PDF'den Word'e dönüştürür.",
        "parameters": {
            "type": "object",
            "properties": {
                "fileUrl": {"type": "string"},
                "chatId": {"type": "string"},
            },
            "required": ["fileUrl"],
        },
    },
    {
        "name": "convert_word_to_pdf",
        "description": "Word'den PDF'e dönüştürür.",
        "parameters": {
            "type": "object",
            "properties": {
                "fileUrl": {"type": "string"},
                "chatId": {"type": "string"},
            },
            "required": ["fileUrl"],
        },
    },
    {
        "name": "convert_excel_to_pdf",
        "description": "Excel'den PDF'e dönüştürür.",
        "parameters": {
            "type": "object",
            "properties": {
                "fileUrl": {"type": "string"},
                "chatId": {"type": "string"},
            },
            "required": ["fileUrl"],
        },
    },
    {
        "name": "convert_pdf_to_excel",
        "description": "PDF'den Excel'e dönüştürür.",
        "parameters": {
            "type": "object",
            "properties": {
                "fileUrl": {"type": "string"},
                "chatId": {"type": "string"},
            },
            "required": ["fileUrl"],
        },
    },
    {
        "name": "convert_pdf_to_ppt",
        "description": "PDF'den PPT'ye dönüştürür.",
        "parameters": {
            "type": "object",
            "properties": {
                "fileUrl": {"type": "string"},
                "chatId": {"type": "string"},
            },
            "required": ["fileUrl"],
        },
    },
    {
        "name": "convert_ppt_to_pdf",
        "description": "PPT'den PDF'e dönüştürür.",
        "parameters": {
            "type": "object",
            "properties": {
                "fileUrl": {"type": "string"},
                "chatId": {"type": "string"},
            },
            "required": ["fileUrl"],
        },
    },
]


