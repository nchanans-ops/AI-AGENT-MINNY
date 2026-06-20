"""
handlers.py — logic 4 โหมด
TEACH / QUERY / REWRITE / EXPIRY
"""

import logging
from telegram import Update, Message
from telegram.ext import ContextTypes

import firebase
import gpt
import r2_storage
import sheets

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────

async def _get_image_bytes(message: Message, context: ContextTypes.DEFAULT_TYPE) -> tuple[bytes, str]:
    """ดึง bytes ของรูปจาก Telegram message คืนค่า (bytes, filename)"""
    photo = message.photo[-1] if message.photo else None
    if not photo:
        return b"", ""
    file = await context.bot.get_file(photo.file_id)
    file_bytes = await file.download_as_bytearray()
    filename = f"{photo.file_id}.jpg"
    return bytes(file_bytes), filename


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

    # ดึงข้อความ (อาจมาจาก caption ถ้าส่งรูป)
    raw_text = message.caption or message.text or ""
    content = _strip_teach_prefix(raw_text)

    if not content and not message.photo:
        await message.reply_text("ส่งข้อมูลมาด้วยนะ เช่น /teach วิธีต่ออายุคือ...")
        return

    # Upload รูปถ้ามี
    image_url = ""
    if message.photo:
        try:
            img_bytes, filename = await _get_image_bytes(message, context)
            image_url = r2_storage.upload_image(img_bytes, filename)
        except Exception as e:
            logger.error(f"R2 upload error: {e}")
            await message.reply_text("อัปโหลดรูปไม่สำเร็จ ลองใหม่นะ")
            return

    if not content and not image_url:
        await message.reply_text("ไม่มีเนื้อหาให้บันทึกเลย ลองใหม่นะ")
        return

    try:
        doc_id = firebase.save_knowledge(
            content=content,
            image_url=image_url,
            added_by=added_by,
        )
        logger.info(f"Knowledge saved: {doc_id} by {added_by}")
        await message.reply_text("บันทึกแล้วนะ 👍")
    except Exception as e:
        logger.error(f"Firebase save error: {e}")
        await message.reply_text("บันทึกไม่สำเร็จ ลองใหม่นะ")


# ──────────────────────────────────────────────
# QUERY
# ──────────────────────────────────────────────

async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    question = message.text or message.caption or ""

    try:
        knowledge_docs = firebase.get_all_knowledge()
        answer = await gpt.answer_query(question, knowledge_docs)
        await message.reply_text(answer)
    except Exception as e:
        logger.error(f"Query error: {e}")
        await message.reply_text("เกิดข้อผิดพลาด ลองใหม่นะ")


# ──────────────────────────────────────────────
# REWRITE
# ──────────────────────────────────────────────

async def handle_rewrite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    raw = message.text or message.caption or ""

    try:
        rewritten = await gpt.rewrite_message(raw)
        await message.reply_text(rewritten)
    except Exception as e:
        logger.error(f"Rewrite error: {e}")
        await message.reply_text("แต่งข้อความไม่สำเร็จ ลองใหม่นะ")


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
