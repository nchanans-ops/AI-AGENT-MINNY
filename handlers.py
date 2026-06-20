"""
handlers.py — logic 4 โหมด
TEACH / QUERY / REWRITE / EXPIRY / REMEMBER
"""

import asyncio
import base64
import logging
import re
from telegram import Update, Message
from telegram.ext import ContextTypes

import d1
import gpt
import sheets

logger = logging.getLogger(__name__)

_ROLE_DISPLAY = {
    "admin": "Admin",
    "staff": "Staff",
    "vip": "VIP",
    "customer": "Customer",
    "other": "Other",
}


# ──────────────────────────────────────────────
# REMEMBER — จำบุคคลจาก @username
# ──────────────────────────────────────────────

def _parse_remember(text: str) -> dict | None:
    """Parse คำสั่งจำบุคคลหลายรูปแบบ:
    - จำ @somchai ชื่อ สมชาย
    - @somchai คือ สมชาย
    - @somchai = สมชาย role admin
    - เปลี่ยน @somchai เป็น สมชาย สมใจ
    - @ann staff
    คืน dict {identifier, name, role} หรือ None
    """
    username_m = re.search(r'@(\w+)', text)
    if not username_m:
        return None
    identifier = '@' + username_m.group(1).lower()

    # เอาส่วนหลัง @username มาแยก name/role
    after = text[username_m.end():].strip()
    # ลบ keyword นำหน้า
    after = re.sub(r'^(?:ชื่อ|คือ|=|ว่า|เป็น|ให้ชื่อ)\s*', '', after, flags=re.I).strip()

    # ดึง role keyword
    role = ''
    role_m = re.search(r'\b(admin|staff|vip|customer|other)\b', after, re.I)
    if role_m:
        role = role_m.group(1).lower()
        after = (after[:role_m.start()] + after[role_m.end():]).strip()
        after = re.sub(r'\brole\b', '', after, flags=re.I).strip()

    # ถ้า after ว่างให้ดูก่อน @username (เช่น "สมชาย คือ @somchai")
    if not after:
        before = text[:username_m.start()].strip()
        before = re.sub(r'^(?:จำ|บันทึก|register|remember|เปลี่ยน)\s*', '', before, flags=re.I).strip()
        before = re.sub(r'\s*(?:ชื่อ|คือ|=|ว่า|เป็น)\s*$', '', before).strip()
        after = before

    name = after.strip()
    if not name and not role:
        return None
    return {'identifier': identifier, 'name': name, 'role': role}


async def handle_remember(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """บันทึก @username → ชื่อ/role ลง D1"""
    message = update.effective_message
    text = (message.text or '').strip()

    parsed = _parse_remember(text)
    if not parsed:
        await message.reply_text(
            "ไม่เข้าใจรูปแบบนะ ลองพิมพ์แบบนี้:\n\n"
            "จำ @somchai ชื่อ สมชาย\n"
            "@somchai คือ สมชาย\n"
            "@somchai = สมชาย role admin\n"
            "เปลี่ยน @ann เป็น อันนา staff"
        )
        return

    try:
        await d1.save_user(
            chat_id=parsed['identifier'],
            name=parsed['name'],
            role=parsed['role'],
            notes='',
        )
        parts = []
        if parsed['name']:
            parts.append(f"ชื่อ: {parsed['name']}")
        if parsed['role']:
            parts.append(f"Role: {_ROLE_DISPLAY.get(parsed['role'], parsed['role'])}")
        await message.reply_text(
            f"จำแล้วนะ {parsed['identifier']}\n" + "\n".join(parts)
        )
        logger.info(f"Saved user profile: {parsed}")
    except Exception as e:
        logger.error(f"Remember error: {e}")
        await message.reply_text("บันทึกไม่สำเร็จ ลองใหม่นะ")


# ──────────────────────────────────────────────
# KB-first verbatim lookup (ใช้ใน route_message ก่อน detect intent)
# ──────────────────────────────────────────────

async def try_kb_verbatim(question: str, chat_id) -> dict | None:
    """ค้น KB ด้วย bidirectional match
    ถ้าเจอ → คืน {"text": ..., "images": [base64, ...]}
    ถ้าไม่เจอ → คืน None
    """
    all_knowledge = await d1.get_all_knowledge()
    matched = [
        doc for doc in all_knowledge
        if _kb_matches(question, doc.get("content", ""))
    ]
    if not matched:
        return None
    parts = [doc.get("content", "").strip() for doc in matched if doc.get("content", "").strip()]
    images = [doc["image_b64"] for doc in matched if doc.get("image_b64")]
    return {
        "text": "\n\n".join(parts) if parts else "",
        "images": images,
    }


# ──────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────

async def _get_image_b64(message: Message, context: ContextTypes.DEFAULT_TYPE) -> str:
    """ดึงรูปจาก Telegram แล้ว encode เป็น base64 string"""
    photo = message.photo[-1] if message.photo else None
    if not photo:
        return ""
    file = await context.bot.get_file(photo.file_id)
    file_bytes = await file.download_as_bytearray()
    return base64.b64encode(bytes(file_bytes)).decode("utf-8")


def _strip_teach_prefix(text: str) -> str:
    """ตัด /teach ออกจากต้นข้อความ"""
    text = text.strip()
    if text.lower().startswith("/teach"):
        text = text[len("/teach"):].strip()
    return text


# ──────────────────────────────────────────────
# TEACH
# ──────────────────────────────────────────────

async def handle_teach(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    added_by = user.username or user.full_name or str(user.id)

    raw_text = message.caption or message.text or ""
    content = _strip_teach_prefix(raw_text)

    if not content and not message.photo:
        await message.reply_text("ส่งข้อมูลมาด้วยนะ เช่น /teach วิธีต่ออายุคือ...")
        return

    # เก็บรูปเป็น base64 ใน D1
    image_b64 = ""
    if message.photo:
        try:
            image_b64 = await _get_image_b64(message, context)
        except Exception as e:
            logger.error(f"Image encode error: {e}")
            await message.reply_text("โหลดรูปไม่สำเร็จ ลองใหม่นะ")
            return

    if not content and not image_b64:
        await message.reply_text("ไม่มีเนื้อหาให้บันทึกเลย ลองใหม่นะ")
        return

    try:
        doc_id = await d1.save_knowledge(
            content=content,
            image_b64=image_b64,
            added_by=added_by,
        )
        logger.info(f"Knowledge saved: id={doc_id} by {added_by}")
        await message.reply_text("บันทึกแล้วนะ 👍")
    except Exception as e:
        logger.error(f"D1 save error: {e}")
        await message.reply_text("บันทึกไม่สำเร็จ ลองใหม่นะ")


# ──────────────────────────────────────────────
# QUERY
# ──────────────────────────────────────────────

def _kb_matches(question: str, content: str) -> bool:
    """Match คำถามกับ KB โดยใช้เฉพาะ keyword บรรทัดแรก
    บรรทัดแรกของ KB ควรเป็น keywords คั่นด้วย comma เช่น:
      "ธีมสลิป, ซื้อธีม, ตั้งค่าธีม"
      "บัญชีรับเงิน"
    ทิศ 1: keyword ใน KB ปรากฏใน question  ("ธีมสลิป" ใน "ขอธีมสลิปหน่อย")
    ทิศ 2: คำใน question ปรากฏใน keyword KB  ("ธีม" ใน keyword "ธีมสลิป")
    → ไม่ค้น body content เพื่อป้องกัน false-positive
    """
    q = question.lower().strip()
    if not q or not content:
        return False

    # ใช้เฉพาะบรรทัดแรกเป็น keyword zone
    first_line = content.strip().split('\n')[0].lower()
    keywords = [k.strip() for k in first_line.split(',') if k.strip()]

    for kw in keywords:
        if len(kw) >= 2:
            if kw in q or q in kw:   # bidirectional substring
                return True
    return False


async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    question = (message.text or message.caption or "").strip()
    chat_id = message.chat_id

    if not question:
        return

    try:
        # ดึง history + knowledge ทั้งหมดพร้อมกัน (2 D1 queries แทน N queries)
        history, all_knowledge = await asyncio.gather(
            d1.get_history(chat_id),
            d1.get_all_knowledge(),
        )

        # Python-side match — เร็วกว่า LIKE และรองรับไทยไม่เว้นวรรค
        matched_docs = [
            doc for doc in all_knowledge
            if _kb_matches(question, doc.get("content", ""))
        ]

        if matched_docs:
            # ✅ เจอ → ตอบ verbatim เป๊ะๆ ไม่ผ่าน GPT เลย
            parts = [doc.get("content", "").strip() for doc in matched_docs if doc.get("content", "").strip()]
            answer = "\n\n".join(parts)
        else:
            # ไม่เจอ → GPT fallback (all_knowledge ดึงมาแล้ว ไม่ต้อง query ซ้ำ)
            answer = await gpt.answer_query(question, all_knowledge, history)

        await message.reply_text(answer)
        await d1.add_message(chat_id, "user", question)
        await d1.add_message(chat_id, "assistant", answer)

    except Exception as e:
        logger.error(f"Query error: {e}")
        await message.reply_text("เกิดข้อผิดพลาด ลองใหม่นะ")


# ──────────────────────────────────────────────
# REWRITE
# ──────────────────────────────────────────────

_EXPIRY_KEYWORDS = ["แจ้งหมดอายุ", "เตือนหมดอายุ", "ต่ออายุบอท", "แจ้งต่ออายุ", "หมดอายุ"]

def _extract_customer_name(text: str) -> str:
    """ดึงชื่อลูกค้าจากข้อความ — หาคำหลัง 'ลูกค้า'"""
    import re
    m = re.search(r"ลูกค้า\s+(.+)", text)
    if m:
        return m.group(1).strip()
    return ""


async def handle_rewrite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    raw = (message.text or message.caption or "").strip()
    chat_id = message.chat_id

    try:
        # ถ้าเป็นข้อความแจ้งหมดอายุ → auto-lookup วันที่จาก Sheet
        prompt = raw
        is_expiry = any(kw in raw for kw in _EXPIRY_KEYWORDS)
        if is_expiry:
            cust_name = _extract_customer_name(raw)
            if cust_name:
                info = await asyncio.get_event_loop().run_in_executor(
                    None, sheets.find_customer_expiry, cust_name
                )
                if info and info.get("expiry"):
                    # inject วันที่เข้าไปใน prompt ให้ GPT รู้
                    prompt = f"{raw}\n[วันหมดอายุของลูกค้า {info['shop']}: {info['expiry']}]"
                elif info is None:
                    prompt = f"{raw}\n[ไม่พบข้อมูลลูกค้าชื่อ '{cust_name}' ในระบบ]"

        history = await d1.get_history(chat_id)
        rewritten = await gpt.rewrite_message(prompt, history)
        await message.reply_text(rewritten)
        await d1.add_message(chat_id, "user", raw)
        await d1.add_message(chat_id, "assistant", rewritten)
    except Exception as e:
        logger.error(f"Rewrite error: {e}")
        await message.reply_text("แต่งข้อความไม่สำเร็จ ลองใหม่นะ")


# ──────────────────────────────────────────────
# LIST — แสดง knowledge ทั้งหมด
# ──────────────────────────────────────────────

async def handle_myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ตอบ Chat ID + Username และ auto-link @username → numeric chat_id"""
    message = update.effective_message
    user = update.effective_user
    chat_id = str(message.chat_id)
    full_name = user.full_name or "-"
    tg_username = f"@{user.username.lower()}" if user.username else None

    linked_msg = ""
    try:
        # ถ้ามี @username → หาใน D1 ว่าเคยบันทึกผ่าน "จำ @username" ไหม
        if tg_username:
            old = await d1.get_user(tg_username)
            if old:
                # ย้ายข้อมูลจาก @username → numeric chat_id
                await d1.save_user(
                    chat_id=chat_id,
                    name=old['name'],
                    role=old['role'],
                    notes=old['notes'],
                )
                await d1.delete_user(tg_username)
                linked_msg = f"\nเชื่อมข้อมูลจาก {tg_username} แล้ว (Role: {_ROLE_DISPLAY.get(old['role'], old['role']) or '-'})"

        # ดึง profile ที่บันทึกอยู่ (ถ้ามี)
        profile = await d1.get_user(chat_id)
        profile_msg = ""
        if profile and (profile.get('name') or profile.get('role')):
            profile_msg = (
                f"\n\nระบบรู้จักคุณว่า:\n"
                f"ชื่อ: {profile['name'] or '-'}\n"
                f"Role: {_ROLE_DISPLAY.get(profile['role'], profile['role']) or '-'}"
            )
    except Exception as e:
        logger.error(f"myid profile lookup error: {e}")
        profile_msg = ""
        linked_msg = ""

    await message.reply_text(
        f"Chat ID ของคุณคือ:\n"
        f"{chat_id}\n\n"
        f"ชื่อ Telegram: {full_name}\n"
        f"Username: {tg_username or '(ไม่มี)'}"
        f"{linked_msg}"
        f"{profile_msg}\n\n"
        f"คัดลอก Chat ID ไปใส่ Dashboard แท็บ 'จำบุคคล' ได้เลย"
    )


async def handle_forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ล้าง conversation history ของ chat นี้"""
    message = update.effective_message
    try:
        await d1.clear_history(message.chat_id)
        await message.reply_text("ลืมหมดแล้วนะ 🧹 เริ่มใหม่ได้เลย")
    except Exception as e:
        logger.error(f"Forget error: {e}")
        await message.reply_text("ล้าง history ไม่สำเร็จ ลองใหม่นะ")


async def handle_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    try:
        docs = await d1.get_all_knowledge()
        if not docs:
            await message.reply_text("ยังไม่มี knowledge เลย ลอง /teach ก่อนได้เลย")
            return

        lines = [f"📚 Knowledge ทั้งหมด ({len(docs)} รายการ)\n"]
        for doc in docs:
            content = doc.get("content", "") or "(ไม่มีข้อความ)"
            has_img = "🖼 " if doc.get("image_b64") else ""
            doc_id = doc.get("id", "?")
            lines.append(f"[{doc_id}] {has_img}{content[:80]}{'...' if len(content) > 80 else ''}")

        lines.append("\nลบรายการ: /delete [id]")
        await message.reply_text("\n".join(lines))
    except Exception as e:
        logger.error(f"List error: {e}")
        await message.reply_text("ดึงข้อมูลไม่สำเร็จ ลองใหม่นะ")


async def handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ลบ knowledge entry ด้วย id — /delete [id]"""
    message = update.effective_message
    args = context.args
    if not args or not args[0].isdigit():
        await message.reply_text("ใส่ id ด้วยนะ เช่น /delete 3\nดู id ได้จาก /list")
        return
    doc_id = int(args[0])
    try:
        ok = await d1.delete_knowledge(doc_id)
        if ok:
            await message.reply_text(f"ลบ entry [{doc_id}] แล้ว ✅")
        else:
            await message.reply_text(f"ไม่เจอ entry [{doc_id}] นะ ลองเช็ก /list ก่อน")
    except Exception as e:
        logger.error(f"Delete error: {e}")
        await message.reply_text("ลบไม่สำเร็จ ลองใหม่นะ")


# ──────────────────────────────────────────────
# CHAT
# ──────────────────────────────────────────────

async def handle_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    text = (message.text or message.caption or "").strip()
    chat_id = message.chat_id

    try:
        # ดึง history + knowledge พร้อมกัน (parallel)
        history, knowledge_docs = await asyncio.gather(
            d1.get_history(chat_id),
            d1.get_all_knowledge(),
        )
        reply = await gpt.chat_reply(text, history, knowledge_docs)

        await message.reply_text(reply)
        await d1.add_message(chat_id, "user", text)
        await d1.add_message(chat_id, "assistant", reply)
    except Exception as e:
        logger.error(f"Chat error: {e}")
        await message.reply_text("อุ๊ย เกิดข้อผิดพลาด ลองใหม่นะ")


# ──────────────────────────────────────────────
# EXPIRY
# ──────────────────────────────────────────────

async def handle_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    text = message.text or message.caption or ""

    try:
        rows = sheets.parse_expiry_query(text)
        reply = sheets.format_expiry_list(rows)
        await message.reply_text(reply)
    except Exception as e:
        logger.error(f"Expiry check error: {e}")
        await message.reply_text("ดึงข้อมูลหมดอายุไม่สำเร็จ ลองใหม่นะ")
