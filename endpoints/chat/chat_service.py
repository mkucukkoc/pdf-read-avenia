from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from functools import partial

import requests
import json
from google.cloud import firestore as firestore_client

from core.firebase import db
from core.useChatPersistence import chat_persistence
from schemas import ChatMessagePayload, ChatRequestPayload
from core.websocket_manager import stream_manager
from endpoints.chat_title.service import generate_chat_title

logger = logging.getLogger("pdf_read_refresh.chat_service")


class ChatService:
    """Service that handles AI chat interactions and persistence."""

    _instance: Optional["ChatService"] = None

    def __init__(self) -> None:
        self._gemini_api_key = os.getenv("GEMINI_API_KEY")
        self._db = db
        self._default_model = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
        self._title_model = os.getenv("CHAT_TITLE_MODEL", self._default_model)
        self._system_instruction = os.getenv(
            "GEMINI_SYSTEM_PROMPT",
            "You are an AI chat. Your name is Avenia.",
        )
        logger.debug("ChatService initialized with model=%s titleModel=%s", self._default_model, self._title_model)
        logger.info("ChatService ready; default=%s title=%s", self._default_model, self._title_model)
        logger.debug("Firestore client configured: %s", bool(self._db))

    @classmethod
    def get_instance(cls) -> "ChatService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def send_message(self, payload: ChatRequestPayload, user_id: str) -> Dict[str, Any]:
        request_id = uuid.uuid4().hex[:8]
        start_time = datetime.now(timezone.utc)

        if not user_id:
            raise ValueError("User ID is required to send chat messages")
        if not payload.messages:
            raise ValueError("messages field must contain at least one message")
        if not self._gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY not configured")

        logger.info(
            "Processing chat send request requestId=%s userId=%s chatId=%s messageCount=%s hasImage=%s imageFileUrl=%s stream=%s",
            request_id,
            user_id,
            payload.chat_id,
            len(payload.messages),
            payload.has_image,
            payload.image_file_url,
            payload.stream,
        )
        message_previews = [
            {
                "role": message.role,
                "preview": (message.content or "")[:500],
                "hasFile": bool(message.file_url),
                "fileUrl": message.file_url,
            }
            for message in payload.messages
        ]
        logger.debug(
            "Chat messages received requestId=%s userId=%s chatId=%s language=%s previews=%s",
            request_id,
            user_id,
            payload.chat_id,
            payload.language or "unknown",
            message_previews,
        )

        if getattr(payload, "skip_user_persist", False):
            logger.debug(
                "Skipping user message persistence per payload flag",
                extra={"chatId": payload.chat_id, "userId": user_id},
            )
        else:
            await self._persist_latest_user_message(user_id=user_id, payload=payload)

        if payload.stream:
            stream_message_id = self._generate_message_id()
            logger.info(
                "Chat send entering streaming mode requestId=%s userId=%s chatId=%s messageId=%s",
                request_id,
                user_id,
                payload.chat_id,
                stream_message_id,
            )
            asyncio.create_task(
                self._handle_streaming_response(
                    user_id=user_id,
                    payload=payload,
                    message_id=stream_message_id,
                    request_id=request_id,
                )
            )
            return {
                "success": True,
                "data": {
                    "streaming": True,
                    "messageId": stream_message_id,
                },
                "message": "Streaming response started",
            }

        logger.debug(
            "Chat send building system instruction requestId=%s chatId=%s language=%s",
            request_id,
            payload.chat_id,
            payload.language,
        )
        system_instruction = self._build_system_instruction(payload.language)
        prompt_text = self._prepare_gemini_prompt(payload.messages, payload.image_file_url, system_instruction)
        logger.debug(
            "Chat prompt prepared requestId=%s userId=%s chatId=%s language=%s promptPreview=%s",
            request_id,
            user_id,
            payload.chat_id,
            payload.language or "unknown",
            prompt_text[:1000],
        )
        logger.info(
            "Calling Gemini text generation requestId=%s chatId=%s model=%s",
            request_id,
            payload.chat_id,
            self._select_model(payload),
        )

        assistant_content = await asyncio.to_thread(
            self._call_gemini_generate_content,
            prompt_text,
            self._select_model(payload),
            system_instruction,
        )
        logger.info(
            "Gemini text generation completed requestId=%s chatId=%s assistantPreview=%s",
            request_id,
            payload.chat_id,
            assistant_content[:200],
        )
        assistant_message = ChatMessagePayload(
            role="assistant",
            content=assistant_content,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        if payload.chat_id:
            await asyncio.to_thread(
                partial(
                    chat_persistence.save_assistant_message,
                    user_id=user_id,
                    chat_id=payload.chat_id,
                    content=assistant_message.content,
                    metadata={
                        "tool": "chat_gemini",
                        "requestId": request_id,
                    },
                )
            )
        else:
            logger.warning(
                "Skipping assistant persistence due to missing chatId",
                extra={"requestId": request_id, "userId": user_id},
            )
        logger.debug(
            "Assistant message persisted requestId=%s chatId=%s messageLen=%s",
            request_id,
            payload.chat_id,
            len(assistant_message.content or ""),
        )

        chat_title = await self._maybe_generate_chat_title(
            user_id,
            payload.chat_id,
            assistant_content,
            payload.language,
        )

        if chat_title and payload.chat_id:
            await asyncio.to_thread(
                partial(
                    chat_persistence.update_chat_metadata,
                    user_id=user_id,
                    chat_id=payload.chat_id,
                    content=None,
                    force_title=chat_title,
                )
            )
        elif chat_title:
            logger.warning(
                "Cannot persist chat title; chatId missing",
                extra={"requestId": request_id, "userId": user_id},
            )
        logger.debug(
            "Chat metadata updated requestId=%s chatId=%s chatTitle=%s",
            request_id,
            payload.chat_id,
            chat_title,
        )

        processing_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        logger.info(
            "Chat response generated requestId=%s userId=%s chatId=%s processingTimeMs=%s",
            request_id,
            user_id,
            payload.chat_id,
            processing_time,
        )

        data: Dict[str, Any] = {
            "message": assistant_message.model_dump(by_alias=True),
        }
        if chat_title:
            data["chatTitle"] = chat_title

        return {
            "success": True,
            "data": data,
            "message": "Chat message processed successfully",
        }

    async def text_to_speech(self, messages: List[ChatMessagePayload]) -> Dict[str, Any]:
        logger.info(
            "Received text-to-speech request messageCount=%s",
            len(messages),
        )
        # Placeholder implementation that mirrors the previous TypeScript behavior.
        audio_url = "https://example.com/audio.mp3"
        return {
            "success": True,
            "data": {"audioUrl": audio_url},
            "message": "Text converted to speech",
        }

    async def get_chat_messages(self, user_id: str, chat_id: str) -> Dict[str, Any]:
        if not user_id:
            raise ValueError("User ID is required to fetch chat messages")
        if not chat_id:
            raise ValueError("chatId is required")

        messages: List[Dict[str, Any]] = []

        if not self._db:
            logger.warning("Firestore client unavailable; returning empty message list")
            return {
                "success": True,
                "data": {"messages": messages},
                "message": "Messages retrieved successfully",
            }

        collection = (
            self._db.collection("users")
            .document(user_id)
            .collection("chats")
            .document(chat_id)
            .collection("messages")
        )

        for doc in collection.order_by("timestamp", direction=firestore_client.Query.ASCENDING).stream():
            data = doc.to_dict() or {}
            data["id"] = doc.id
            if "timestamp" in data:
                data["timestamp"] = self._serialize_timestamp(data["timestamp"])
            messages.append(data)

        logger.info(
            "Fetched chat messages userId=%s chatId=%s count=%s",
            user_id,
            chat_id,
            len(messages),
        )

        return {
            "success": True,
            "data": {"messages": messages},
            "message": "Messages retrieved successfully",
        }

    async def create_chat(self, user_id: str, title: Optional[str]) -> Dict[str, Any]:
        if not user_id:
            raise ValueError("User ID is required to create chat")

        chat_id = f"chat_{uuid.uuid4().hex}"
        chat_title = title.strip() if title else "Yeni Chat"

        if self._db:
            chat_ref = (
                self._db.collection("users")
                .document(user_id)
                .collection("chats")
                .document(chat_id)
            )
            data = {
                "id": chat_id,
                "title": chat_title,
                "createdAt": firestore_client.SERVER_TIMESTAMP,
                "updatedAt": firestore_client.SERVER_TIMESTAMP,
                "lastMessage": "",
                "userId": user_id,
            }
            chat_ref.set(data)

        logger.info(
            "Created chat session userId=%s chatId=%s title=%s",
            user_id,
            chat_id,
            chat_title,
        )

        return {
            "success": True,
            "data": {"chatId": chat_id},
            "message": "Chat created successfully",
        }

    # ----- Internal helpers -------------------------------------------------

    async def _handle_streaming_response(
        self,
        user_id: str,
        payload: ChatRequestPayload,
        message_id: str,
        request_id: str,
    ) -> None:
        logger.info(
            "Starting streaming response requestId=%s userId=%s chatId=%s messageId=%s",
            request_id,
            user_id,
            payload.chat_id,
            message_id,
        )
        try:
            system_instruction = self._build_system_instruction(payload.language)
            prompt_text = self._prepare_gemini_prompt(payload.messages, payload.image_file_url, system_instruction)
            logger.debug(
                "Chat prompt prepared (stream) requestId=%s userId=%s chatId=%s language=%s promptPreview=%s",
                request_id,
                user_id,
                payload.chat_id,
                payload.language or "unknown",
                prompt_text[:1000],
            )
            model = self._select_model(payload)

            # Real streaming: consume streamGenerateContent deltas and forward as websocket chunks
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

            def producer():
                try:
                    for delta in self._call_gemini_generate_content_stream(
                        prompt_text,
                        model,
                        system_instruction,
                    ):
                        asyncio.run_coroutine_threadsafe(queue.put(delta), loop)
                except Exception as exc:
                    logger.exception(
                        "Gemini streaming producer error requestId=%s chatId=%s",
                        request_id,
                        payload.chat_id,
                    )
                finally:
                    asyncio.run_coroutine_threadsafe(queue.put(None), loop)

            # Run producer in a thread concurrently; consume queue as soon as items arrive
            producer_task = asyncio.create_task(asyncio.to_thread(producer))

            final_content = ""
            while True:
                delta = await queue.get()
                if delta is None:
                    break
                final_content += delta
                logger.debug(
                    "Streaming delta accumulated chatId=%s messageId=%s deltaLen=%s totalLen=%s deltaPreview=%s",
                    payload.chat_id,
                    message_id,
                    len(delta),
                    len(final_content),
                    delta[:120],
                )
                await stream_manager.emit_chunk(
                    payload.chat_id,
                    {
                        "chatId": payload.chat_id,
                        "messageId": message_id,
                        "content": final_content,
                        "delta": delta,
                        "isFinal": False,
                    },
                )

            # ensure producer thread is finished
            await producer_task

            assistant_message = ChatMessagePayload(
                role="assistant",
                content=final_content,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            logger.info(
                "Final streaming content ready requestId=%s chatId=%s messageId=%s contentLength=%s",
                request_id,
                payload.chat_id,
                message_id,
                len(final_content),
            )

            if payload.chat_id:
                await asyncio.to_thread(
                    partial(
                        chat_persistence.save_assistant_message,
                        user_id=user_id,
                        chat_id=payload.chat_id,
                        content=assistant_message.content,
                        metadata={
                            "tool": "chat_gemini",
                            "requestId": request_id,
                            "stream": True,
                        },
                        message_id=message_id,
                    )
                )

            chat_title = await self._maybe_generate_chat_title(
                user_id,
                payload.chat_id,
                final_content,
                payload.language,
            )

            if chat_title and payload.chat_id:
                await asyncio.to_thread(
                    partial(
                        chat_persistence.update_chat_metadata,
                        user_id=user_id,
                        chat_id=payload.chat_id,
                        content=None,
                        force_title=chat_title,
                    )
                )

            await stream_manager.emit_chunk(
                payload.chat_id,
                {
                    "chatId": payload.chat_id,
                    "messageId": message_id,
                    "content": final_content,
                    "delta": None,
                    "isFinal": True,
                },
            )

            logger.info(
                "Streaming chat response generated requestId=%s userId=%s chatId=%s messageId=%s",
                request_id,
                user_id,
                payload.chat_id,
                message_id,
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.exception(
                "Streaming response failed requestId=%s userId=%s chatId=%s messageId=%s",
                request_id,
                user_id,
                payload.chat_id,
                message_id,
            )
            await stream_manager.emit_chunk(
                payload.chat_id,
                {
                    "chatId": payload.chat_id,
                    "messageId": message_id,
                    "isFinal": True,
                    "error": "stream_failed",
                    "content": "",
                },
            )
            await stream_manager.emit_chunk(
                payload.chat_id,
                {
                    "chatId": payload.chat_id,
                    "messageId": message_id,
                    "isFinal": True,
                    "error": "stream_failed",
                },
            )

    def _generate_message_id(self) -> str:
        return f"assistant_{uuid.uuid4().hex}"

    def _prepare_gemini_prompt(
        self,
        messages: List[ChatMessagePayload],
        image_file_url: Optional[str],
        system_instruction: Optional[str] = None,
    ) -> str:
        lines: List[str] = []
        # Always prepend system instruction
        sys_ins = system_instruction or self._system_instruction
        if sys_ins:
            lines.append(f"System: {sys_ins}")
        for message in messages:
            role = message.role or "user"
            content = (message.content or "").strip()
            file_url = message.file_url or image_file_url
            if file_url and file_url not in content:
                content = f"{content}\n[Dosya Bağlantısı]: {file_url}".strip()
            prefix = "System" if role == "system" else ("Assistant" if role == "assistant" else "User")
            lines.append(f"{prefix}: {content}")
        return "\n".join(lines)

    def _call_gemini_generate_content(self, prompt_text: str, model: str, system_instruction: Optional[str] = None) -> str:
        if not self._gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY not configured")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self._gemini_api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt_text}]}],
        }
        if system_instruction:
            payload["system_instruction"] = {"parts": [{"text": system_instruction}]}
        resp = requests.post(url, json=payload, timeout=120)
        resp.encoding = "utf-8"
        logger.info(
            "Gemini text request completed status=%s bodyPreview=%s",
            resp.status_code,
            (resp.text or "")[:400],
        )
        if not resp.ok:
            raise RuntimeError(f"Gemini text generation failed: {resp.status_code} {resp.text[:400]}")
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        parts = (candidates[0].get("content") or {}).get("parts") or []
        texts: List[str] = []
        for part in parts:
            if "text" in part and isinstance(part["text"], str):
                texts.append(part["text"])
        return "\n".join(texts).strip()

    def _call_gemini_generate_content_stream(
        self, prompt_text: str, model: str, system_instruction: Optional[str] = None
    ):
        """
        Streams text deltas from Gemini (streamGenerateContent). Yields delta strings.
        """
        if not self._gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY not configured")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:streamGenerateContent?alt=sse&key={self._gemini_api_key}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt_text}]}],
        }
        if system_instruction:
            payload["system_instruction"] = {"parts": [{"text": system_instruction}]}

        resp = requests.post(
            url,
            json=payload,
            timeout=120,
            stream=True,
            headers={"Accept": "text/event-stream"},
        )
        # Ensure UTF-8 decoding for Turkish characters
        resp.encoding = "utf-8"
        logger.info(
            "Gemini text stream request started status=%s model=%s promptPreview=%s",
            resp.status_code,
            model,
            prompt_text[:120],
        )
        if not resp.ok:
            body_preview = (resp.text or "")[:400]
            raise RuntimeError(f"Gemini text stream failed: {resp.status_code} {body_preview}")

        def _iter_deltas():
            first_event_preview = None
            chunk_count = 0
            buffer: list[str] = []

            def flush_event():
                nonlocal first_event_preview, chunk_count
                if not buffer:
                    return
                data_str = "\n".join(buffer).strip()
                buffer.clear()
                if not data_str:
                    return
                if first_event_preview is None:
                    first_event_preview = data_str[:200]
                try:
                    obj = json.loads(data_str)
                except json.JSONDecodeError:
                    logger.debug("Gemini stream non-JSON event preview=%s", data_str[:200])
                    return
                logger.debug("Gemini stream chunk parsed keys=%s", list(obj.keys()))
                candidates = obj.get("candidates") or []
                for candidate in candidates:
                    parts = (candidate.get("content") or {}).get("parts") or []
                    for part in parts:
                        text = part.get("text")
                        if isinstance(text, str) and text:
                            chunk_count += 1
                            logger.debug(
                                "Gemini stream delta len=%s preview=%s",
                                len(text),
                                text[:120],
                            )
                            yield text

            for raw_line in resp.iter_lines(decode_unicode=True):
                line = raw_line if isinstance(raw_line, str) else raw_line.decode("utf-8", errors="ignore")
                if line is None:
                    continue
                line = line.rstrip("\r")
                if not line:
                    yield from flush_event()
                    continue
                if line.startswith("data:"):
                    buffer.append(line[len("data:") :].strip())
                elif line.startswith(":"):
                    # comment/keep-alive
                    continue
                else:
                    buffer.append(line.strip())

            # flush any remaining buffered data
            yield from flush_event()

            logger.info(
                "Gemini stream completed firstEventPreview=%s chunkCount=%s",
                first_event_preview,
                chunk_count,
            )

        return _iter_deltas()

    def _build_system_instruction(self, language_code: Optional[str]) -> str:
        base = self._system_instruction or ""
        if language_code:
            lang_part = f" Respond ONLY in {language_code}."
            return (base + lang_part).strip()
        return base

    async def _maybe_generate_chat_title(
        self,
        user_id: str,
        chat_id: str,
        assistant_content: str,
        language_code: Optional[str],
    ) -> Optional[str]:
        # Eğer bu sohbete daha önce başlık atanmışsa tekrar üretme
        if not chat_id or not self._db:
            return None
        try:
            chat_ref = (
                self._db.collection("users")
                .document(user_id)
                .collection("chats")
                .document(chat_id)
            )
            snapshot = chat_ref.get()
            if snapshot.exists:
                data = snapshot.to_dict() or {}
                # Daha önce başlık üretilmişse ya da mevcut başlık varsa yeniden üretme
                existing_title = (data.get("title") or "").strip()
                if data.get("hasChatTitle") or existing_title:
                    return None
        except Exception:
            # Başlık kontrolü başarısız olsa bile üretim akışını engelleme
            logger.debug("Chat title check failed; continuing to generate", exc_info=True)

        content = assistant_content.strip()
        if len(content) < 12:
            return None

        try:
            generated = await generate_chat_title(content, language_code)
            if generated:
                logger.info(
                    "Generated chat title userId=%s chatId=%s title=%s source=openai_gpt35",
                    user_id,
                    chat_id,
                    generated,
                )
            return generated
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.exception("Failed to generate chat title: %s", exc)
            return None

    async def _persist_latest_user_message(
        self,
        *,
        user_id: str,
        payload: ChatRequestPayload,
    ) -> None:
        if not payload.chat_id:
            logger.debug(
                "Skipping user message persistence; chatId missing",
                extra={"userId": user_id},
            )
            return

        for message in reversed(payload.messages):
            if message.role != "user":
                continue
            content = (message.content or "").strip()
            if not content:
                continue
            metadata = getattr(message, "metadata", None) or {}
            if metadata.get("isTemporary"):
                continue
            merged_metadata = dict(metadata)
            merged_metadata.setdefault("source", "chat_request")
            merged_metadata["stream"] = payload.stream
            await asyncio.to_thread(
                partial(
                    chat_persistence.save_user_message,
                    user_id=user_id,
                    chat_id=payload.chat_id,
                    content=content,
                    file_name=message.file_name,
                    file_url=message.file_url or payload.image_file_url,
                    metadata=merged_metadata,
                )
            )
            break

    def _select_model(self, payload: ChatRequestPayload) -> str:
        """
        Choose Gemini text model. Image flag is ignored; we always use _default_model.
        """
        return self._default_model

    def _serialize_timestamp(self, value: Any) -> str:
        dt = self._deserialize_timestamp(value)
        if not dt:
            return datetime.now(timezone.utc).isoformat()
        return dt.isoformat()

    def _deserialize_timestamp(self, value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc)
        if hasattr(value, "to_datetime"):
            return value.to_datetime().astimezone(timezone.utc)
        return None

    # ----- Chat management (rename / favorite / delete) ----------------------

    def rename_chat(self, user_id: str, chat_id: str, title: str) -> Dict[str, Any]:
        if not self._db:
            raise RuntimeError("Firestore client unavailable")
        if not user_id or not chat_id:
            raise ValueError("user_id and chat_id are required")
        clean_title = (title or "").strip()
        if not clean_title:
            raise ValueError("title is required")

        chat_ref = (
            self._db.collection("users")
            .document(user_id)
            .collection("chats")
            .document(chat_id)
        )
        chat_ref.set(
            {
                "title": clean_title[:120],
                "hasChatTitle": True,
                "updatedAt": firestore_client.SERVER_TIMESTAMP,
            },
            merge=True,
        )
        logger.info("Chat renamed userId=%s chatId=%s title=%s", user_id, chat_id, clean_title)
        return {"chatId": chat_id, "title": clean_title}

    def set_favorite(self, user_id: str, chat_id: str, favorite: bool) -> Dict[str, Any]:
        if not self._db:
            raise RuntimeError("Firestore client unavailable")
        if not user_id or not chat_id:
            raise ValueError("user_id and chat_id are required")

        chat_ref = (
            self._db.collection("users")
            .document(user_id)
            .collection("chats")
            .document(chat_id)
        )
        chat_ref.set(
            {
                "favorites": bool(favorite),
                "updatedAt": firestore_client.SERVER_TIMESTAMP,
            },
            merge=True,
        )
        logger.info("Chat favorite updated userId=%s chatId=%s favorite=%s", user_id, chat_id, favorite)
        return {"chatId": chat_id, "favorites": bool(favorite)}

    def delete_chat(self, user_id: str, chat_id: str) -> Dict[str, Any]:
        if not self._db:
            raise RuntimeError("Firestore client unavailable")
        if not user_id or not chat_id:
            raise ValueError("user_id and chat_id are required")

        chat_ref = (
            self._db.collection("users")
            .document(user_id)
            .collection("chats")
            .document(chat_id)
        )
        # Soft delete marker; avoids expensive recursive deletes.
        chat_ref.set(
            {
                "deleted": True,
                "deletedAt": firestore_client.SERVER_TIMESTAMP,
                "updatedAt": firestore_client.SERVER_TIMESTAMP,
            },
            merge=True,
        )
        logger.info("Chat marked deleted userId=%s chatId=%s", user_id, chat_id)
        return {"chatId": chat_id, "deleted": True}


chat_service = ChatService.get_instance()

__all__ = ["chat_service", "ChatService"]

