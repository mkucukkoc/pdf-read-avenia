from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from firebase_admin import firestore

from .firebase import db


logger = logging.getLogger("pdf_read_refresh.core.chat_persistence")
_TITLE_SANITIZE_PATTERN = re.compile(r"[^a-zA-Z0-9ğüşöçıİĞÜŞÖÇ\s]")


def _clean_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return _TITLE_SANITIZE_PATTERN.sub("", value).strip()


def _trim(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


@dataclass(frozen=True)
class MessagePayload:
    role: str
    content: str
    file_name: Optional[str] = None
    file_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    is_temporary: bool = False
    message_id: Optional[str] = None


class ChatPersistenceService:
    """
    Firestore yazma işlemlerini tek merkezden yöneten servis.
    Frontend artık doğrudan Firestore'a dokunmayacağı için tüm CRUD buradan geçecek.
    """

    def __init__(self) -> None:
        self._db = db

    def _ensure_db(self):
        if not self._db:
            raise RuntimeError("Firebase client is not initialized")
        return self._db

    @staticmethod
    def _resolve_user(user_id: Optional[str]) -> str:
        return user_id or "anonymous"

    @staticmethod
    def _derive_title(content: str) -> str:
        clean = _clean_text(content)
        if not clean:
            clean = "Chat"
        return _trim(clean, 60)

    def _chat_ref(self, user_id: str, chat_id: str):
        db_client = self._ensure_db()
        return (
            db_client.collection("users")
            .document(self._resolve_user(user_id))
            .collection("chats")
            .document(chat_id)
        )

    def _messages_ref(self, user_id: str, chat_id: str):
        return self._chat_ref(user_id, chat_id).collection("messages")

    def ensure_chat_document(
        self,
        *,
        user_id: str,
        chat_id: str,
        initial_content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        chat_ref = self._chat_ref(user_id, chat_id)
        snapshot = chat_ref.get()
        if snapshot.exists:
            return

        clean_title = self._derive_title(initial_content or "")
        payload: Dict[str, Any] = {
            "createdAt": firestore.SERVER_TIMESTAMP,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "title": clean_title,
            "hasChatTitle": False,
        }
        if initial_content:
            payload["lastMessage"] = _trim(initial_content, 150)
        if metadata:
            payload.update(metadata)

        chat_ref.set(payload, merge=True)
        logger.info(
            "Chat document created",
            extra={"chatId": chat_id, "userId": user_id},
        )

    def update_chat_metadata(
        self,
        *,
        user_id: str,
        chat_id: str,
        content: Optional[str],
        force_title: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not content and not force_title and not extra:
            return

        update_payload: Dict[str, Any] = {"timestamp": firestore.SERVER_TIMESTAMP}

        if force_title:
            update_payload["title"] = _trim(force_title, 60)
            update_payload["hasChatTitle"] = True
        elif content:
            cleaned = _clean_text(content)
            if cleaned:
                update_payload.setdefault("title", self._derive_title(cleaned))
            update_payload["lastMessage"] = _trim(content, 150)

        if extra:
            update_payload.update(extra)

        self._chat_ref(user_id, chat_id).set(update_payload, merge=True)

    def append_message(
        self,
        *,
        user_id: str,
        chat_id: str,
        message: MessagePayload,
    ) -> str:
        payload: Dict[str, Any] = {
            "role": message.role,
            "content": message.content,
            "timestamp": firestore.SERVER_TIMESTAMP,
        }
        if message.file_name:
            payload["fileName"] = message.file_name
        if message.file_url:
            payload["fileUrl"] = message.file_url
        if message.metadata:
            payload["metadata"] = message.metadata
        if message.is_temporary:
            payload.setdefault("metadata", {})
            payload["metadata"]["isTemporary"] = True

        messages_ref = self._messages_ref(user_id, chat_id)
        if not message.message_id:
            result = messages_ref.add(payload)
            doc_ref = result[0] if isinstance(result, tuple) else result
            doc_id = getattr(doc_ref, "id", None) or ""
        else:
            messages_ref.document(message.message_id).set(payload, merge=True)
            doc_id = message.message_id

        logger.debug(
            "Message persisted",
            extra={
                "chatId": chat_id,
                "userId": user_id,
                "role": message.role,
                "messageId": doc_id,
            },
        )
        return doc_id

    def save_user_message(
        self,
        *,
        user_id: str,
        chat_id: str,
        content: str,
        file_name: Optional[str] = None,
        file_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        is_temporary: bool = False,
    ) -> str:
        self.ensure_chat_document(
            user_id=user_id,
            chat_id=chat_id,
            initial_content=content,
        )
        self.update_chat_metadata(user_id=user_id, chat_id=chat_id, content=content)
        return self.append_message(
            user_id=user_id,
            chat_id=chat_id,
            message=MessagePayload(
                role="user",
                content=content,
                file_name=file_name,
                file_url=file_url,
                metadata=metadata,
                is_temporary=is_temporary,
            ),
        )

    def save_assistant_message(
        self,
        *,
        user_id: str,
        chat_id: str,
        content: str,
        file_name: Optional[str] = None,
        file_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        message_id: Optional[str] = None,
    ) -> str:
        self.ensure_chat_document(
            user_id=user_id,
            chat_id=chat_id,
            initial_content=content,
        )
        self.update_chat_metadata(user_id=user_id, chat_id=chat_id, content=content)
        return self.append_message(
            user_id=user_id,
            chat_id=chat_id,
            message=MessagePayload(
                role="assistant",
                content=content,
                file_name=file_name,
                file_url=file_url,
                metadata=metadata,
                message_id=message_id,
            ),
        )

    def save_system_message(
        self,
        *,
        user_id: str,
        chat_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        self.ensure_chat_document(
            user_id=user_id,
            chat_id=chat_id,
            initial_content=content,
        )
        return self.append_message(
            user_id=user_id,
            chat_id=chat_id,
            message=MessagePayload(
                role="system",
                content=content,
                metadata=metadata,
            ),
        )

    def persist_temp_messages(
        self,
        *,
        user_id: str,
        chat_id: str,
        temp_messages: Optional[list[Dict[str, Any]]],
    ) -> None:
        if not temp_messages:
            return
        for message in temp_messages:
            content = (message.get("content") or "").strip()
            if not content:
                continue
            self.save_user_message(
                user_id=user_id,
                chat_id=chat_id,
                content=content,
                file_name=message.get("file_name"),
                file_url=message.get("file_url"),
                metadata={"source": "temp_prompt"},
                is_temporary=True,
            )


chat_persistence = ChatPersistenceService()

__all__ = ["chat_persistence", "ChatPersistenceService"]

