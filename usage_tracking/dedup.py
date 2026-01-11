from typing import Dict

from google.cloud import firestore


def acquire_request_lock(
    db: firestore.Client,
    request_id: str,
    metadata: Dict,
) -> bool:
    """Atomically create request_dedup/{requestId}.

    Returns:
        True if the lock was acquired (first request).
        False if the requestId already exists.
    """

    doc_ref = db.collection("request_dedup").document(request_id)

    @firestore.transactional
    def _txn(transaction: firestore.Transaction) -> bool:
        snapshot = doc_ref.get(transaction=transaction)
        if snapshot.exists:
            return False
        transaction.set(doc_ref, metadata, merge=True)
        return True

    transaction = db.transaction()
    return _txn(transaction)
