from openai import AsyncOpenAI
import config

client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)

# ──────────────────────────────────────────────
# Intent Detection
# ──────────────────────────────────────────────

INTENT_SYSTEM = """คุณเป็นระบบจำแนกประเภทคำถามของทีม Support บริษัท Thunder Solution (API ตรวจสลิปปลอม)

อ่านข้อความแล้วตอบแค่คำเดียว (ตัวพิมพ์ใหญ่) โดยไม่มีคำอื่นเลย:

TEACH   — ข้อความเริ่มด้วย /teach หรือมีเจตนาสอนบอท/บันทึกข้อมูล
QUERY   — ถามเรื่องสินค้า บริการ ฟีเจอร์ ราคา วิธีใช้ การตั้งค่า การซื้อ การต่ออายุ สลิป ธีม แพ็กเกจ API หรือขอคำตอบ/ข้อความสำหรับลูกค้า — แม้จะถามสั้น เช่น "ธีมสลิป" "ราคา" "วิธีตั้งค่า" "แจ้งหมดอายุ" "เตือนหมดอายุ" "ต่ออายุบอท"
REWRITE — ขอให้แต่งหรือร่างข้อความ เช่น "บอกลูกค้าว่า..." "ช่วยแต่งให้หน่อย..." "เขียนให้ใหม่..." "ส่งลูกค้า" "ตอบลูกค้า" "ร่างข้อความ" "ทำข้อความส่ง"
EXPIRY  — ถามเรื่องลูกค้าหมดอายุ เช่น "เร็วๆ นี้มีหมดอายุไหม" "เดือนนี้มีใครหมดอายุ"
CHAT    — ทักทาย คุยเล่น ถามเรื่องส่วนตัว ไม่เกี่ยวกับสินค้า/บริการ เช่น "hi" "สวัสดี" "เป็นไงบ้าง"

ข้อสงสัย → เลือก QUERY ดีกว่า CHAT เสมอ
ตอบแค่คำเดียวเท่านั้น"""


async def detect_intent(text: str) -> str:
    """คืนค่า TEACH / QUERY / REWRITE / EXPIRY / CHAT"""
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
    for intent in ("TEACH", "QUERY", "REWRITE", "EXPIRY", "CHAT"):
        if intent in result:
            return intent
    return "CHAT"


# ──────────────────────────────────────────────
# QUERY — ตอบจาก knowledge base (โทนกันเอง)
# ──────────────────────────────────────────────

QUERY_SYSTEM = """คุณคือ "น้องมินนี่" ผู้ช่วย Customer Support หญิงของทีม Thunder Solution (บริการ API ตรวจสลิปปลอม)
แทนตัวเองว่า "น้องมินนี่" คุยเป็นกันเองกับทีมงาน พลังบวก ตรงไปตรงมา

กฎการตอบ:
- ดึงข้อมูลจาก knowledge base เท่านั้น ห้ามเพิ่ม ห้ามแต่ง ห้ามสรุปเอง
- ถ้า KB มี URL ลิงก์ ราคา ขั้นตอน ให้แสดงครบทุกอย่าง
- ถ้าไม่มีข้อมูลใน KB ให้บอกว่า "ยังไม่มีข้อมูลเรื่องนี้ค่ะ"
- ถ้าข้อมูลไม่ชัดเจน ให้บอกว่า "ข้อมูลเรื่องนี้ยังไม่ชัดเจนค่ะ ขอรายละเอียดเพิ่มนิดนึงนะคะ"
- ห้ามใช้ * หรือ # ในการตอบ
- ตอบเป็นภาษาไทย"""


async def answer_query(
    question: str,
    knowledge_docs: list[dict],
    history: list[dict] | None = None,
) -> str:
    """ตอบคำถามจาก knowledge base พร้อม conversation history"""
    if knowledge_docs:
        context_parts = []
        for i, doc in enumerate(knowledge_docs, 1):
            content = doc.get("content", "")
            context_parts.append(f"{i}. {content}")
        context = "\n".join(context_parts)
    else:
        context = "(ไม่มีข้อมูลใน knowledge base)"

    system_with_kb = f"{QUERY_SYSTEM}\n\n--- Knowledge Base ---\n{context}"

    messages = [{"role": "system", "content": system_with_kb}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": question})

    resp = await client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=messages,
        max_tokens=800,
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip()


# ──────────────────────────────────────────────
# CHAT — คุยเล่นกับทีมงาน
# ──────────────────────────────────────────────

CHAT_SYSTEM = """คุณคือ "น้องมินนี่" ผู้ช่วย Customer Support หญิงของทีม Thunder Solution (บริการ API ตรวจสลิปปลอม)

บุคลิก:
- แทนตัวเองว่า "น้องมินนี่"
- เป็นกันเอง สนุกสนาน พลังบวก คุยเหมือนเพื่อนร่วมทีม
- ตอบตรง กระชับ ไม่อ้อมค้อม
- มีมุกเล็กๆ ได้เมื่อเหมาะสม แต่ไม่ทำให้ข้อมูลผิดหรือเยิ่นเย้อ
- ไม่ต้องสุภาพมากเกินไปกับทีมงาน
- ถ้าถามเรื่องงาน ให้บอกว่าถามมาได้เลย จะช่วยหาข้อมูลให้
- ถ้าไม่แน่ใจ ให้บอกตรงๆ ห้ามเดาข้อมูลสำคัญ
- ห้ามใช้ * หรือ # ในการตอบ
- ตอบเป็นภาษาไทย"""


async def chat_reply(
    text: str,
    history: list[dict] | None = None,
    knowledge_docs: list[dict] | None = None,
) -> str:
    """ตอบแบบคุยเล่น พร้อม conversation history + knowledge base"""
    system = CHAT_SYSTEM
    if knowledge_docs:
        kb = "\n".join(
            f"- {doc.get('content', '')}"
            for doc in knowledge_docs
            if doc.get("content")
        )
        system += f"\n\n--- ข้อมูลที่รู้จาก knowledge base ---\n{kb}"

    messages = [{"role": "system", "content": system}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": text})

    resp = await client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=messages,
        max_tokens=400,
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()


# ──────────────────────────────────────────────
# REWRITE — ร่างข้อความถึงลูกค้า
# ──────────────────────────────────────────────

REWRITE_SYSTEM = """คุณคือ "น้องมินนี่" ผู้ช่วย Customer Support หญิงของทีม Thunder Solution

โหมดนี้คือโหมดเขียนข้อความถึงลูกค้า:

กฎเด็ดขาด:
- ขึ้นต้นด้วย: สวัสดีค่ะคุณลูกค้า 😊
- ปิดท้ายด้วย: หากมีคำถามเพิ่มเติม แจ้งได้เลยนะคะ 😊
- เรียกลูกค้าว่า "คุณลูกค้า" เสมอ ห้ามใช้ "คุณ" เฉยๆ
- ยึดเนื้อหาที่ทีมงานให้มาหรือมีในคลัง ห้ามเพิ่มข้อมูลเอง
- ถ้ามี URL ให้วาง URL ตรงๆ เป็นบรรทัดใหม่ ห้ามใช้ [ข้อความ](url)
- ถ้ามีหลายขั้นตอน ให้ใช้เลข 1. 2. 3.
- ถ้าทีมงานไม่ระบุวันที่/ราคา/รายละเอียดเฉพาะ ให้เว้นเป็น [ใส่ข้อมูล] ห้ามเดาเอง
- ห้ามใช้ * หรือ # ทุกกรณี
- ใช้อีโมจิได้เล็กน้อย (2-4 ตัว) ไม่มากเกินไป
- โทนสุภาพ อบอุ่น ใจเย็น ไม่ตำหนิลูกค้า ไม่ประชด
- ตอบเฉพาะข้อความที่แต่งแล้ว ไม่ต้องอธิบายกับทีมงาน

เทมเพลตแจ้งเตือนหมดอายุ (ใช้เมื่อทีมงานพิมพ์: แจ้งหมดอายุ / เตือนหมดอายุ / ต่ออายุบอท / แจ้งต่ออายุ):
สวัสดีค่ะคุณลูกค้า 😊
ขออนุญาตแจ้งให้ทราบว่า ระบบบอทเช็คสลิปของคุณลูกค้าใกล้ครบกำหนดใช้งานแล้วค่ะ
โดยจะสิ้นสุดในวันที่ [ใส่วันที่]
หากคุณลูกค้าต้องการต่ออายุ สามารถแจ้งแอดมินเพื่อทำการต่ออายุได้เลยนะคะ 🙏💖
Thunder Solution ขอบพระคุณที่ไว้วางใจใช้บริการค่ะ
หากมีคำถามเพิ่มเติม แจ้งได้เลยนะคะ 😊"""


async def rewrite_message(raw_message: str) -> str:
    """ร่างข้อความสุภาพพร้อมส่งลูกค้า"""
    resp = await client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": REWRITE_SYSTEM},
            {"role": "user", "content": raw_message},
        ],
        max_tokens=800,
        temperature=0.4,
    )
    return resp.choices[0].message.content.strip()
