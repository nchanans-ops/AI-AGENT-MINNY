"""
d1.py — Cloudflare D1 knowledge base
เชื่อมผ่าน Cloudflare REST API (Workers AI / D1 HTTP API)
"""

import asyncio
import httpx
from datetime import datetime, timezone
import config

_BASE = (
    f"https://api.cloudflare.com/client/v4/accounts"
    f"/{config.CF_ACCOUNT_ID}/d1/database/{config.CF_D1_DATABASE_ID}/query"
)
_HEADERS = {
    "Authorization": f"Bearer {config.CF_API_TOKEN}",
    "Content-Type": "application/json",
}


async def _query(sql: str, params: list = None):
    """ส่ง SQL ไป D1 แล้วคืน result rows"""
    body = {"sql": sql}
    if params:
        body["params"] = params

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(_BASE, headers=_HEADERS, json=body)
        resp.raise_for_status()
        data = resp.json()

    if not data.get("success"):
        errors = data.get("errors", [])
        raise RuntimeError(f"D1 error: {errors}")

    results = data.get("result", [])
    if results:
        return results[0].get("results", [])
    return []


async def init_table():
    """สร้าง tables ทั้งหมดถ้ายังไม่มี"""
    await _query("""
        CREATE TABLE IF NOT EXISTS knowledge (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            content    TEXT    NOT NULL DEFAULT '',
            image_b64  TEXT    NOT NULL DEFAULT '',
            added_by   TEXT    NOT NULL DEFAULT '',
            created_at TEXT    NOT NULL
        )
    """)
    await _query("""
        CREATE TABLE IF NOT EXISTS conversations (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id    TEXT    NOT NULL,
            role       TEXT    NOT NULL,
            content    TEXT    NOT NULL,
            created_at TEXT    NOT NULL
        )
    """)
    await _query("CREATE INDEX IF NOT EXISTS idx_conv_chat ON conversations(chat_id)")
    await _query("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            chat_id    TEXT    PRIMARY KEY,
            name       TEXT    NOT NULL DEFAULT '',
            role       TEXT    NOT NULL DEFAULT '',
            notes      TEXT    NOT NULL DEFAULT '',
            updated_at TEXT    NOT NULL
        )
    """)


# ──────────────────────────────────────────────
# User Profiles (จำบุคคล)
# ──────────────────────────────────────────────

async def save_user(chat_id: str, name: str = "", role: str = "", notes: str = "") -> None:
    """บันทึกหรืออัปเดต user profile"""
    now = datetime.now(timezone.utc).isoformat()
    await _query(
        """INSERT INTO user_profiles (chat_id, name, role, notes, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(chat_id) DO UPDATE SET
             name=excluded.name, role=excluded.role,
             notes=excluded.notes, updated_at=excluded.updated_at""",
        [str(chat_id), name, role, notes, now],
    )


async def get_all_users() -> list[dict]:
    """ดึง user profiles ทั้งหมด เรียงตามอัปเดตล่าสุด"""
    return await _query(
        "SELECT chat_id, name, role, notes, updated_at FROM user_profiles ORDER BY updated_at DESC"
    )


async def get_user(chat_id: str) -> dict | None:
    """ดึง user profile เดียว"""
    rows = await _query(
        "SELECT chat_id, name, role, notes, updated_at FROM user_profiles WHERE chat_id = ?",
        [str(chat_id)],
    )
    return rows[0] if rows else None


async def delete_user(chat_id: str) -> bool:
    """ลบ user profile"""
    rows = await _query(
        "DELETE FROM user_profiles WHERE chat_id = ? RETURNING chat_id",
        [str(chat_id)],
    )
    return len(rows) > 0


async def save_knowledge(
    content: str,
    image_b64: str = "",
    added_by: str = "",
) -> int:
    """บันทึก knowledge ใหม่ คืนค่า id
    image_b64 = base64-encoded bytes ของรูป (ถ้ามี)
    """
    now = datetime.now(timezone.utc).isoformat()
    rows = await _query(
        "INSERT INTO knowledge (content, image_b64, added_by, created_at) "
        "VALUES (?, ?, ?, ?) RETURNING id",
        [content, image_b64, added_by, now],
    )
    return rows[0]["id"] if rows else -1


async def get_all_knowledge() -> list[dict]:
    """ดึง knowledge ทั้งหมด เรียงล่าสุดก่อน"""
    return await _query(
        "SELECT id, content, image_b64, added_by, created_at "
        "FROM knowledge ORDER BY id DESC"
    )


# ──────────────────────────────────────────────
# Conversation Memory
# ──────────────────────────────────────────────

HISTORY_LIMIT = 10  # เก็บกี่ข้อความล่าสุดต่อ chat


async def add_message(chat_id: str | int, role: str, content: str) -> None:
    """บันทึก message ลง conversations แล้ว trim เหลือ HISTORY_LIMIT"""
    now = datetime.now(timezone.utc).isoformat()
    await _query(
        "INSERT INTO conversations (chat_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        [str(chat_id), role, content, now],
    )
    # trim — เก็บแค่ HISTORY_LIMIT ล่าสุด
    await _query(
        """DELETE FROM conversations WHERE chat_id = ? AND id NOT IN (
               SELECT id FROM conversations WHERE chat_id = ?
               ORDER BY id DESC LIMIT ?
           )""",
        [str(chat_id), str(chat_id), HISTORY_LIMIT],
    )


async def get_history(chat_id: str | int) -> list[dict]:
    """ดึง conversation history ล่าสุด เรียงจากเก่า→ใหม่"""
    rows = await _query(
        "SELECT role, content FROM conversations WHERE chat_id = ? ORDER BY id ASC",
        [str(chat_id)],
    )
    return rows  # [{"role": "user"/"assistant", "content": "..."}]


async def clear_history(chat_id: str | int) -> None:
    """ลบ history ของ chat นั้นทั้งหมด"""
    await _query("DELETE FROM conversations WHERE chat_id = ?", [str(chat_id)])


async def delete_knowledge(doc_id: int) -> bool:
    """ลบ knowledge entry ด้วย id คืน True ถ้าลบสำเร็จ"""
    rows = await _query(
        "DELETE FROM knowledge WHERE id = ? RETURNING id",
        [doc_id],
    )
    return len(rows) > 0


async def search_knowledge(keyword: str) -> list[dict]:
    """full-text search แบบ LIKE"""
    return await _query(
        "SELECT id, content, image_b64, added_by, created_at "
        "FROM knowledge WHERE content LIKE ? ORDER BY id DESC",
        [f"%{keyword}%"],
    )


async def find_by_keywords(keywords: list[str]) -> list[dict]:
    """ค้นหา knowledge ด้วยหลาย keyword พร้อมกัน (parallel) คืนผลที่ไม่ซ้ำ"""
    if not keywords:
        return []
    results_list = await asyncio.gather(
        *[search_knowledge(kw) for kw in keywords],
        return_exceptions=False,
    )
    seen_ids: set = set()
    merged: list[dict] = []
    for results in results_list:
        for doc in results:
            if doc["id"] not in seen_ids:
                seen_ids.add(doc["id"])
                merged.append(doc)
    return merged
