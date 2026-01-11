from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from core.tone_instructions import ToneKey, build_tone_instruction


def _default_system_prompt() -> str:
    return os.getenv("GEMINI_SYSTEM_PROMPT", "You are an AI chat. Your name is Avenia.")


def _default_response_style() -> str:
    return os.getenv("DEFAULT_RESPONSE_STYLE", "cheerful and adaptive")


def resolve_response_style(response_style: Optional[str], tone_key: Optional[ToneKey]) -> Optional[str]:
    if response_style and response_style.strip():
        return response_style.strip()
    if tone_key:
        return str(tone_key)
    fallback = _default_response_style()
    return fallback.strip() if fallback else None


def build_system_message(
    *,
    language: Optional[str],
    tone_key: Optional[ToneKey],
    response_style: Optional[str] = None,
    include_response_style: bool = True,
    include_followup: bool = False,
    followup_language: Optional[str] = None,
    base_instruction: Optional[str] = None,
) -> Optional[str]:
    base = (base_instruction or _default_system_prompt()).strip()
    if not base:
        base = _default_system_prompt()

    style = resolve_response_style(response_style, tone_key) if include_response_style else None
    segments: List[str] = [base]
    if style:
        segments.append(f"Use the response style: {style}.")
    if language:
        segments.append(f"Respond ONLY in {language}.")
    if include_followup:
        followup_lang = followup_language or language or "the same language"
        segments.append(
            "Always end your response with a concise, relevant follow-up question to the user, "
            f"in {followup_lang}."
        )

    tone_instruction = build_tone_instruction(tone_key, language)
    system_text = " ".join(segment for segment in segments if segment).strip()
    if tone_instruction:
        return f"{system_text}\n{tone_instruction}".strip()
    return system_text or None


def build_prompt_text(system_message: Optional[str], user_text: str) -> str:
    system_part = f"System: {system_message}".strip() if system_message else "System:"
    user_part = f"User: {user_text}".strip() if user_text else "User:"
    return f"{system_part}\n{user_part}".strip()


def merge_parts_with_system(parts: List[Dict[str, Any]], system_message: Optional[str]) -> List[Dict[str, Any]]:
    if not system_message:
        return parts
    text_fragments: List[str] = []
    first_text_index: Optional[int] = None
    for idx, part in enumerate(parts):
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            if first_text_index is None:
                first_text_index = idx
            text_fragments.append(part.get("text", "").strip())

    user_text = "\n".join([text for text in text_fragments if text]).strip()
    combined_text = build_prompt_text(system_message, user_text)

    new_parts: List[Dict[str, Any]] = []
    inserted = False
    for idx, part in enumerate(parts):
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            if not inserted:
                new_parts.append({"text": combined_text})
                inserted = True
            continue
        new_parts.append(part)
    if not inserted:
        new_parts.insert(0, {"text": combined_text})
    return new_parts


__all__ = [
    "build_prompt_text",
    "build_system_message",
    "merge_parts_with_system",
    "resolve_response_style",
]
