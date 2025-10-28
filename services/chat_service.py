from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.cloud import firestore as firestore_client
from openai import OpenAI

from ..firebase import db
from ..schemas import ChatMessagePayload, ChatRequestPayload

logger = logging.getLogger("pdf_read_refresh.chat_service")


class ChatService:
    """Service that handles AI chat interactions and persistence."""

    _instance: Optional["ChatService"] = None

    def __init__(self) -> None:
        self._client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self._db = db
        self._default_model = os.getenv("FINE_TUNED_MODEL_ID", "gpt-3.5-turbo")
        self._title_model = os.getenv("CHAT_TITLE_MODEL", self._default_model)

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
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OpenAI API key not configured")

        logger.info(
            "Processing chat send request",
            extra={
                "requestId": request_id,
                "userId": user_id,
                "chatId": payload.chat_id,
                "messageCount": len(payload.messages),
                "hasImage": payload.has_image,
                "imageFileUrl": payload.image_file_url,
            },
        )

        openai_messages = self._prepare_openai_messages(payload.messages, payload.image_file_url)

        response = await asyncio.to_thread(
            self._client.chat.completions.create,
            model=self._select_model(payload),
            messages=openai_messages,
            temperature=0.7,
        )

        choice = response.choices[0].message
        assistant_content = (choice.content or "").strip()
        assistant_message = ChatMessagePayload(
            role="assistant",
            content=assistant_content,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        await asyncio.to_thread(
            self._save_message_to_firestore,
            user_id,
            payload.chat_id,
            assistant_message,
        )

        chat_title = await self._maybe_generate_chat_title(user_id, payload.chat_id, assistant_content)

        await asyncio.to_thread(
            self._update_chat_metadata,
            user_id,
            payload.chat_id,
            assistant_content,
            chat_title,
        )

        processing_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        logger.info(
            "Chat response generated",
            extra={
                "requestId": request_id,
                "userId": user_id,
                "chatId": payload.chat_id,
                "processingTimeMs": processing_time,
            },
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
            "Received text-to-speech request",
            extra={"messageCount": len(messages)},
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
            "Fetched chat messages",
            extra={"userId": user_id, "chatId": chat_id, "count": len(messages)},
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
            "Created chat session",
            extra={"userId": user_id, "chatId": chat_id, "title": chat_title},
        )

        return {
            "success": True,
            "data": {"chatId": chat_id},
            "message": "Chat created successfully",
        }

    # ----- Internal helpers -------------------------------------------------

    def _prepare_openai_messages(
        self,
        messages: List[ChatMessagePayload],
        image_file_url: Optional[str],
    ) -> List[Dict[str, str]]:
        prepared: List[Dict[str, str]] = []
        for message in messages:
            content = (message.content or "").strip()
            file_url = message.file_url or image_file_url
            if file_url and file_url not in content:
                content = f"{content}\n[Dosya Bağlantısı]: {file_url}".strip()
            prepared.append({"role": message.role, "content": content})
        return prepared

    def _save_message_to_firestore(
        self,
        user_id: str,
        chat_id: str,
        message: ChatMessagePayload,
    ) -> None:
        if not self._db:
            logger.debug("Skipping Firestore save; client not available")
            return

        collection = (
            self._db.collection("users")
            .document(user_id)
            .collection("chats")
            .document(chat_id)
            .collection("messages")
        )

        message_data = message.model_dump(by_alias=True)
        message_data["timestamp"] = firestore_client.SERVER_TIMESTAMP

        recent = (
            collection.order_by("timestamp", direction=firestore_client.Query.DESCENDING)
            .limit(5)
            .stream()
        )
        for doc in recent:
            data = doc.to_dict() or {}
            if data.get("role") != message.role:
                continue
            if data.get("content") != message.content:
                continue
            timestamp = data.get("timestamp")
            if not timestamp:
                continue
            existing_time = self._deserialize_timestamp(timestamp)
            if not existing_time:
                continue
            if (datetime.now(timezone.utc) - existing_time).total_seconds() < 10:
                logger.info(
                    "Skipping duplicate message save",
                    extra={"userId": user_id, "chatId": chat_id},
                )
                return

        collection.add(message_data)

    def _update_chat_metadata(
        self,
        user_id: str,
        chat_id: str,
        last_message: str,
        chat_title: Optional[str],
    ) -> None:
        if not self._db:
            return

        chat_ref = (
            self._db.collection("users")
            .document(user_id)
            .collection("chats")
            .document(chat_id)
        )

        data: Dict[str, Any] = {
            "lastMessage": last_message[:500],
            "updatedAt": firestore_client.SERVER_TIMESTAMP,
        }
        if chat_title:
            data.setdefault("title", chat_title)

        chat_ref.set({"id": chat_id, "userId": user_id}, merge=True)
        chat_ref.update(data)

    async def _maybe_generate_chat_title(
        self,
        user_id: str,
        chat_id: str,
        assistant_content: str,
    ) -> Optional[str]:
        content = assistant_content.strip()
        if len(content) < 12:
            return None

        prompt = (
            "You are naming an AI chat conversation. Generate a short, concise "
            "title (max 6 words) that summarizes the following assistant reply. "
            "Return only the title without quotes."
        )

        try:
            response = await asyncio.to_thread(
                self._client.chat.completions.create,
                model=self._title_model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": content[:500]},
                ],
                max_tokens=32,
                temperature=0.5,
            )
            generated = (response.choices[0].message.content or "").strip()
            if generated:
                logger.info(
                    "Generated chat title",
                    extra={"userId": user_id, "chatId": chat_id, "title": generated},
                )
                return generated
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.exception("Failed to generate chat title: %s", exc)
        return None

    def _select_model(self, payload: ChatRequestPayload) -> str:
        if payload.has_image:
            return os.getenv("CHAT_IMAGE_MODEL", "gpt-4o")
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


chat_service = ChatService.get_instance()

__all__ = ["chat_service", "ChatService"]
