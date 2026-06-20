# Minny Support Bot 

Telegram bot สำหรับทีม Support ของ Thunder Solution (API ตรวจสลิปปลอม)
ทีมถามบอท → บอทสร้างคำตอบ → ทีม copy ไปส่งลูกค้า

---

## 4 โหมด

| โหมด | วิธีใช้ | ผลลัพธ์ |
|---|---|---|
| TEACH | `/teach [ข้อมูล]` หรือส่งรูป + caption | บันทึกลง Firestore |
| QUERY | ถามแบบธรรมชาติ | ตอบจาก knowledge base (โทนกันเอง) |
| REWRITE | "บอกลูกค้าว่า..." / "ช่วยแต่งให้..." | ข้อความสุภาพ พร้อม copy ส่งลูกค้า |
| EXPIRY | "เดือนนี้มีหมดอายุไหม" | ลิสต์จาก Google Sheets |

---

## Setup

### 1. Clone & Install

```bash
git clone https://github.com/nchanans-ops/AI-AGENT-MINNY.git
cd AI-AGENT-MINNY
pip install -r requirements.txt
```

### 2. เตรียม Credentials

copy `.env.example` → `.env` แล้วใส่ค่าทั้งหมด

```bash
cp .env.example .env
```

| ตัวแปร | วิธีได้มา |
|---|---|
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) → `/newbot` |
| `OPENAI_API_KEY` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| `FIREBASE_SERVICE_ACCOUNT_PATH` | [Firebase Console](https://console.firebase.google.com) → Project Settings → Service Accounts → **Generate new private key** → วางไฟล์ JSON ชื่อ `firebase-service-account.json` |
| `GOOGLE_SHEETS_CRED_PATH` | [Google Cloud Console](https://console.cloud.google.com/iam-admin/serviceaccounts) → สร้าง Service Account → Keys → Add Key → JSON → วางไฟล์ชื่อ `google-sheets-cred.json` |
| `GOOGLE_SHEET_ID` | เปิด Google Sheet → copy ID จาก URL: `docs.google.com/spreadsheets/d/**<ID>**/edit` |
| `CF_R2_BUCKET_NAME` | [Cloudflare Dashboard](https://dash.cloudflare.com) → R2 |
| `CF_R2_ACCESS_KEY_ID` | Cloudflare → R2 → **Manage R2 API Tokens** |
| `CF_R2_SECRET_ACCESS_KEY` | (ได้พร้อมกับ Access Key ID) |
| `CF_R2_ACCOUNT_ID` | Cloudflare Dashboard → มุมขวาบน |
| `CF_R2_PUBLIC_URL` | Cloudflare → R2 → Bucket → Settings → Public Access URL |

> **สำคัญ:** หลังสร้าง Google Service Account ต้อง Share Google Sheet ให้ email ใน field `client_email` ของไฟล์ JSON ด้วยสิทธิ์ **Viewer** ขึ้นไป

### 3. ตั้งค่า Google Sheet

ชื่อ column ใน Sheet ต้องตรงดังนี้:

```
ชื่อร้าน | เบอร์/Line | แพ็กเกจ | วันเริ่ม | วันหมดอายุ | สถานะ
```

รูปแบบวันที่รองรับ: `DD/MM/YYYY`, `DD-MM-YYYY`, `YYYY-MM-DD`

### 4. รัน

```bash
python main.py
```

---

## โครงสร้างไฟล์

```
├── main.py          ← entry point + routing
├── config.py        ← โหลด .env
├── handlers.py      ← logic 4 โหมด
├── gpt.py           ← intent detection + query + rewrite
├── firebase.py      ← CRUD Firestore
├── sheets.py        ← ดึงข้อมูลหมดอายุ
├── r2_storage.py    ← upload รูป Cloudflare R2
├── .env.example     ← template credentials
└── requirements.txt
```

---

## Tech Stack

- **Bot:** python-telegram-bot v20
- **AI:** GPT-4o mini (OpenAI)
- **Knowledge Base:** Firebase Firestore
- **รูปภาพ:** Cloudflare R2
- **หมดอายุ:** Google Sheets
