import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timezone
import config

# Init Firebase (เรียกครั้งเดียว)
if not firebase_admin._apps:
    cred = credentials.Certificate(config.FIREBASE_SERVICE_ACCOUNT_PATH)
    firebase_admin.initialize_app(cred)

db = firestore.client()
_col = db.collection(config.FIRESTORE_COLLECTION)


def save_knowledge(content: str, image_url: str = "", added_by: str = "") -> str:
    """บันทึกความรู้ใหม่ คืนค่า document ID"""
    doc_ref = _col.document()
    doc_ref.set({
        "content": content,
        "image_url": image_url,
        "added_by": added_by,
        "timestamp": datetime.now(timezone.utc),
    })
    return doc_ref.id


def get_all_knowledge() -> list[dict]:
    """ดึง knowledge ทั้งหมด เรียงตาม timestamp ล่าสุดก่อน"""
    docs = _col.order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
    return [{"id": d.id, **d.to_dict()} for d in docs]


def search_knowledge(keyword: str) -> list[dict]:
    """
    ดึง knowledge ทั้งหมดแล้ว filter ใน Python
    (Firestore ไม่รองรับ full-text search โดยตรง)
    """
    all_docs = get_all_knowledge()
    keyword_lower = keyword.lower()
    return [
        doc for doc in all_docs
        if keyword_lower in doc.get("content", "").lower()
    ]
