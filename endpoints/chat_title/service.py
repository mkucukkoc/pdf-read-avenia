from __future__ import annotations

import asyncio
import logging
from typing import Optional

from core.openai_client import get_client


logger = logging.getLogger("pdf_read_refresh.chat_title_service")

DEFAULT_TITLE_MODEL = "gpt-3.5-turbo"


async def generate_chat_title(text: str, language: Optional[str]) -> Optional[str]:
    """
    Generate a short chat title using an inexpensive OpenAI model.
    Returns None if generation fails.
    """
    content = (text or "").strip()
    if len(content) < 12:
        return None

    model = DEFAULT_TITLE_MODEL
    system_prompt = (
        "You are a helpful assistant that creates very short conversation titles. "
        "Return ONLY the title text, max 6 words, no quotes, no emojis."
    )
    if language:
        system_prompt += f" Write the title in {language}."

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content[:800]},
    ]

    try:
        client = get_client()
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=model,
            messages=messages,
            max_tokens=32,
            temperature=0.6,
        )
        choice = response.choices[0] if response.choices else None
        title = (choice.message.content or "").strip() if choice and choice.message else ""
        if not title:
            return None
        # Clean extra lines
        title = title.split("\n")[0].strip()
        logger.info("Chat title generated via OpenAI model=%s title=%s", model, title)
        return title
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Chat title generation failed: %s", exc)
        return None


__all__ = ["generate_chat_title", "DEFAULT_TITLE_MODEL"]
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from core.openai_client import get_client


logger = logging.getLogger("pdf_read_refresh.chat_title.service")

DEFAULT_TITLE_MODEL = os.getenv("CHAT_TITLE_MODEL_OVERRIDE") or os.getenv("CHAT_TITLE_MODEL") or "gpt-3.5-turbo"


def _build_prompt(content: str, language_code: Optional[str]) -> str:
    language = (language_code or "tr").lower()
    language_label = {
        "tr": "Turkish",
        "en": "English",
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "pt": "Portuguese",
        "ru": "Russian",
        "it": "Italian",
    }.get(language[:2], "Turkish")

    return (
        "You are naming an AI chat conversation. Generate a short, concise title "
        f"in {language_label} (max 6 words) that summarizes the following assistant reply. "
        "Return only the title without quotes and without additional commentary."
        f"\n\nAssistant reply:\n{content.strip()}"
    )


async def generate_chat_title_text(content: str, language_code: Optional[str]) -> Optional[str]:
    trimmed = (content or "").strip()
    if len(trimmed) < 12:
        return None

    client = get_client()
    prompt = _build_prompt(trimmed, language_code)

    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=DEFAULT_TITLE_MODEL,
            temperature=0.2,
            max_tokens=32,
            messages=[
                {"role": "system", "content": "Name conversations with short, catchy titles."},
                {"role": "user", "content": prompt},
            ],
        )
        choice = (response.choices or [None])[0]
        if not choice or not getattr(choice, "message", None):
            return None
        result = (choice.message.content or "").strip()
        if result.startswith('"') and result.endswith('"'):
            result = result[1:-1].strip()
        return result or None
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Chat title generation failed: %s", exc)
        return None


__all__ = ["generate_chat_title_text"]

