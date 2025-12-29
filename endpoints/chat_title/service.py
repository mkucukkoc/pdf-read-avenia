from __future__ import annotations

import asyncio
import logging
from typing import Optional

from core.openai_client import get_client


logger = logging.getLogger("pdf_read_refresh.chat_title.service")

# Fallback model; can be overridden via env CHAT_TITLE_MODEL
DEFAULT_TITLE_MODEL = "gpt-3.5-turbo"


async def generate_chat_title(text: str, language: Optional[str]) -> Optional[str]:
    """
    Generate a short chat title using an inexpensive OpenAI model.
    Returns None if generation fails.
    """
    content = (text or "").strip()
    if len(content) < 12:
        return None

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
            model=DEFAULT_TITLE_MODEL,
            messages=messages,
            max_tokens=32,
            temperature=0.6,
        )
        choice = response.choices[0] if response.choices else None
        title = (choice.message.content or "").strip() if choice and choice.message else ""
        if not title:
          return None
        title = title.split("\n")[0].strip()
        logger.info("Chat title generated via OpenAI model=%s title=%s", DEFAULT_TITLE_MODEL, title)
        return title
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Chat title generation failed: %s", exc)
        return None


__all__ = ["generate_chat_title", "DEFAULT_TITLE_MODEL"]



