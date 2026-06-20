import os
from dotenv import load_dotenv

load_dotenv()

# ===== Telegram =====
TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]

# ===== OpenAI =====
OPENAI_API_KEY: str = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL: str = "gpt-4o-mini"

# ===== Cloudflare (shared) =====
CF_ACCOUNT_ID: str = os.environ["CF_ACCOUNT_ID"]
CF_API_TOKEN: str = os.environ["CF_API_TOKEN"]

# ===== Cloudflare D1 (knowledge base + รูป base64) =====
CF_D1_DATABASE_ID: str = os.environ["CF_D1_DATABASE_ID"]

# ===== Google Sheets =====
GOOGLE_SHEETS_CRED_PATH: str = os.environ["GOOGLE_SHEETS_CRED_PATH"]
GOOGLE_SHEET_ID: str = os.environ["GOOGLE_SHEET_ID"]
