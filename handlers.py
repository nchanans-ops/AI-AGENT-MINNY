"""
handlers.py — logic 4 โหมด
TEACH / QUERY / REWRITE / EXPIRY
"""

import asyncio
import base64
import logging
from telegram import Update, Message
from telegram.ext import ContextTypes

import d1
import gpt
import sheets

logger = logging.getLogger(__name__)


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
    """Bidirectional keyword match — รองรับภาษาไทยที่ไม่เว้นวรรค
    ทิศ 1: คำจาก KB content ปรากฏอยู่ในคำถาม  (เช่น "ธีมสลิป" ใน "ขอธีมสลิปหน่อย")
    ทิศ 2: คำจากคำถามปรากฏอยู่ใน KB content  (เช่น "ธีม" ใน content ที่มี "ธีมสลิป")
    """
    q = question.lower().strip()
    c = content.lower().strip()
    if not c:
        return False
    for word in c.split():          # คำจาก KB → หาในคำถาม
        if len(word) >= 3 and word in q:
            return True
    for word in q.split():          # คำจากคำถาม → หาใน KB
        if len(word) >= 3 and word in c:
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
