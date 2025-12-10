import base64
import base64
import json
import logging
import os
from typing import Optional

import firebase_admin
from firebase_admin import credentials, firestore

logger = logging.getLogger("pdf_read_refresh.firebase")

def _initialize_app() -> None:
    if firebase_admin._apps:
        return

    encoded_credentials = os.getenv("FIREBASE_SERVICE_ACCOUNT_BASE64")
    if not encoded_credentials:
        logger.warning("FIREBASE_SERVICE_ACCOUNT_BASE64 not set; Firebase features disabled")
        return

    try:
        decoded = base64.b64decode(encoded_credentials).decode("utf-8")
        cred_dict = json.loads(decoded)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred, {
            'storageBucket': cred_dict.get('storageBucket') or 'aveniaapp.firebasestorage.app'
        })
        logger.info("Firebase app initialized successfully for pdf-read-fresh service")
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Failed to initialize Firebase: %s", exc)


def get_firestore_client() -> Optional[firestore.Client]:
    try:
        _initialize_app()
        if not firebase_admin._apps:
            return None
        return firestore.client()
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Failed to create Firestore client: %s", exc)
        return None


db = get_firestore_client()

__all__ = ["db"]



