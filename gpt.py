from openai import AsyncOpenAI
import config

client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)

# ──────────────────────────────────────────────
# Intent Detection
# ──────────────────────────────────────────────

INTENT_SYSTEM = """คุณเป็นระบบจำแนกประเภทคำถามของทีม Support

อ่านข้อความแล้วตอบแค่คำเดียว (ตัวพิมพ์ใหญ่) โดยไม่มีคำอื่นเลย:

TEACH   — ข้อความเริ่มด้วย /teach หรือมีเจตนาสอนบอท/บันทึกข้อมูล
QUERY   — ถามหาข้อมูล วิธีตอบลูกค้า หรือขอความรู้จาก knowledge base
REWRITE — ขอให้แต่งข้อความ เช่น "บอกลูกค้าว่า..." "ช่วยแต่งให้หน่อย..." "เขียนให้ใหม่..."
EXPIRY  — ถามเรื่องลูกค้าหมดอายุ เช่น "เร็วๆ นี้มีหมดอายุไหม" "เดือนนี้มีใครหมดอายุ"

ตอบแค่คำเดียวเท่านั้น"""


async def detect_intent(text: str) -> str:
    """คืนค่า TEACH / QUERY / REWRITE / EXPIRY"""
    resp = await client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": INTENT_SYSTEM},
            {"role": "user", "content": text},
        ],
        max_tokens=10,
        temperature=0,
    )
    result = resp.choices[0].message.content.strip().upper()
    # Fallback ถ้า GPT ตอบเพี้ยน
    for intent in ("TEACH", "QUERY", "REWRITE", "EXPIRY"):
        if intent in result:
            return intent
    return "QUERY"


# ──────────────────────────────────────────────
# QUERY — ตอบจาก knowledge base (โทนกันเอง)
# ──────────────────────────────────────────────

QUERY_SYSTEM = """คุณเป็นผู้ช่วยภายในทีม Support ของ Thunder Solution (บริการ API ตรวจสลิปปลอม)

กฎการตอบ:
- คุยแบบกันเองกับพนักงาน ตอบตรงๆ ไม่อ้อมค้อม
- ยึดข้อมูลจาก knowledge base ที่ให้มาเท่านั้น อย่าแต่งเพิ่ม
- ถ้าไม่มีข้อมูลในฐาน ให้บอกตรงๆ ว่า "ยังไม่มีข้อมูลส่วนนี้นะ ลองสอนบอทก่อนได้เลย"
- ห้ามใช้ * หรือ # ในการตอบ
- ตอบเป็นภาษาไทย"""


async def answer_query(question: str, knowledge_docs: list[dict]) -> str:
    """ตอบคำถามจาก knowledge base"""
    if knowledge_docs:
        context_parts = []
        for i, doc in enumerate(knowledge_docs, 1):
            content = doc.get("content", "")
            image_url = doc.get("image_url", "")
            entry = f"{i}. {content}"
            if image_url:
                entry += f"\n   [มีรูปประกอบ: {image_url}]"
            context_parts.append(entry)
        context = "\n".join(context_parts)
    else:
        context = "(ไม่มีข้อมูลใน knowledge base)"

    prompt = f"""ข้อมูลที่มีใน knowledge base:
{context}

คำถามจากพนักงาน: {question}"""

    resp = await client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": QUERY_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        max_tokens=800,
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip()


# ──────────────────────────────────────────────
# REWRITE — แต่งข้อความให้ลูกค้า (โทนสุภาพ)
# ──────────────────────────────────────────────

REWRITE_SYSTEM = """คุณเป็นผู้ช่วยแต่งข้อความให้ทีม Support ของ Thunder Solution

กฎเด็ดขาด:
- ห้ามใช้ * (asterisk) ทุกกรณี — ห้ามทำตัวหนา ห้ามทำ bullet ด้วย *
- ห้ามใช้ # (hashtag) ทุกกรณี — ห้ามทำหัวข้อ
- ใช้อีโมจิพอประมาณ (2-4 ตัวต่อข้อความ) ไม่มากเกินไป
- ภาษาสุภาพ อบอุ่น ใส่ใจลูกค้า
- ยึดเนื้อหาที่พนักงานบอกมา อย่าเพิ่มข้อมูลเอง
- ตอบเฉพาะข้อความที่แต่งแล้ว ไม่ต้องอธิบายหรือนำหน้าด้วยอะไรทั้งนั้น"""


async def rewrite_message(raw_message: str) -> str:
    """รีไรท์ข้อความให้สุภาพ พร้อมส่งลูกค้า"""
    resp = await client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": REWRITE_SYSTEM},
            {"role": "user", "content": raw_message},
        ],
        max_tokens=600,
        temperature=0.5,
    )
    return resp.choices[0].message.content.strip()
