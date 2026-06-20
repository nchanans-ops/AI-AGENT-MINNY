"""
main.py — Thunder Support Bot
Entry point: รับ message → detect intent → route ไป handler ที่ถูกต้อง
"""

import base64
import logging
import asyncio

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

import config
import d1
import gpt
import handlers

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Router หลัก
# ──────────────────────────────────────────────

async def route_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """จุดเข้าหลัก: detect intent แล้ว route"""
    message = update.effective_message
    if not message:
        return

    text = message.text or message.caption or ""
    if not text.strip():
        # ข้อความที่ไม่มีข้อความเลย (เช่น รูปล้วนๆ ไม่มี caption)
        await message.reply_text("ส่ง caption มาด้วยนะ เช่น /teach [ข้อมูล] หรือพิมพ์คำถาม")
        return

    # /teach สั้นๆ โดยไม่ตรวจ intent
    if text.strip().lower().startswith("/teach"):
        await handlers.handle_teach(update, context)
        return

    # ── KB-first: ค้น knowledge base ก่อน detect intent ──
    # ถ้าเจอ → ตอบ verbatim ทันที ไม่เสีย GPT call เลย
    # ไม่เจอ → detect intent ตามปกติ
    try:
        kb_answer = await handlers.try_kb_verbatim(text, message.chat_id)
    except Exception as e:
        logger.error(f"KB lookup error: {e}")
        kb_answer = None

    if kb_answer is not None:
        logger.info(f"[{update.effective_user.id}] KB-hit verbatim text={text[:60]!r}")
        answer_text = kb_answer["text"]
        images = kb_answer["images"]
        # ส่งรูปแรกพร้อม caption ถ้ามี ส่วนรูปที่เหลือส่งแยก
        if images:
            first_img = base64.b64decode(images[0])
            await message.reply_photo(photo=first_img, caption=answer_text or None)
            for img_b64 in images[1:]:
                await message.reply_photo(photo=base64.b64decode(img_b64))
        elif answer_text:
            await message.reply_text(answer_text)
        await d1.add_message(message.chat_id, "user", text)
        await d1.add_message(message.chat_id, "assistant", answer_text)
        return

    # ── ไม่เจอใน KB → detect intent ──
    try:
        intent = await gpt.detect_intent(text)
    except Exception as e:
        logger.error(f"Intent detection failed: {e}")
        await message.reply_text("เกิดข้อผิดพลาดในการวิเคราะห์คำถาม ลองใหม่นะ")
        return

    logger.info(f"[{update.effective_user.id}] intent={intent} text={text[:60]!r}")

    if intent == "TEACH":
        await handlers.handle_teach(update, context)
    elif intent == "REMEMBER":
        await handlers.handle_remember(update, context)
    elif intent == "REWRITE":
        await handlers.handle_rewrite(update, context)
    elif intent == "EXPIRY":
        await handlers.handle_expiry(update, context)
    elif intent == "QUERY":
        await handlers.handle_query(update, context)
    else:  # CHAT (default)
        await handlers.handle_chat(update, context)


# ──────────────────────────────────────────────
# เริ่มบอท
# ──────────────────────────────────────────────

async def post_init(app) -> None:
    """สร้าง D1 table ตอน startup (ถ้ายังไม่มี)"""
    await d1.init_table()
    logger.info("D1 table ready")


def main() -> None:
    app = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # commands
    app.add_handler(CommandHandler("list", handlers.handle_list))
    app.add_handler(CommandHandler("forget", handlers.handle_forget))
    app.add_handler(CommandHandler("delete", handlers.handle_delete))
    app.add_handler(CommandHandler("myid", handlers.handle_myid))

    # รับทั้ง text และ รูปภาพ (พร้อม caption)
    app.add_handler(
        MessageHandler(
            filters.TEXT | filters.PHOTO,
            route_message,
        )
    )

    logger.info("Thunder Support Bot เริ่มทำงาน...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
