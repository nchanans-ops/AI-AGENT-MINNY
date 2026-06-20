"""
main.py — Thunder Support Bot
Entry point: รับ message → detect intent → route ไป handler ที่ถูกต้อง
"""

import logging
import asyncio

from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes,
)

import config
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

    # /teach สั้นๆ โดยไม่ตรวจ intent (เร็วกว่า + ชัวร์กว่า)
    if text.strip().lower().startswith("/teach"):
        await handlers.handle_teach(update, context)
        return

    # ส่งไป GPT classify
    try:
        intent = await gpt.detect_intent(text)
    except Exception as e:
        logger.error(f"Intent detection failed: {e}")
        await message.reply_text("เกิดข้อผิดพลาดในการวิเคราะห์คำถาม ลองใหม่นะ")
        return

    logger.info(f"[{update.effective_user.id}] intent={intent} text={text[:60]!r}")

    if intent == "TEACH":
        await handlers.handle_teach(update, context)
    elif intent == "REWRITE":
        await handlers.handle_rewrite(update, context)
    elif intent == "EXPIRY":
        await handlers.handle_expiry(update, context)
    else:  # QUERY (default)
        await handlers.handle_query(update, context)


# ──────────────────────────────────────────────
# เริ่มบอท
# ──────────────────────────────────────────────

def main() -> None:
    app = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .build()
    )

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
