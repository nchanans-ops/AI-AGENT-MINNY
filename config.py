import os
from dotenv import load_dotenv

load_dotenv()

# ===== Telegram =====
TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]

# ===== OpenAI =====
OPENAI_API_KEY: str = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL: str = "gpt-4o-mini"

# ===== Firebase =====
FIREBASE_SERVICE_ACCOUNT_PATH: str = os.environ["FIREBASE_SERVICE_ACCOUNT_PATH"]
FIRESTORE_COLLECTION: str = "knowledge"

# ===== Google Sheets =====
GOOGLE_SHEETS_CRED_PATH: str = os.environ["GOOGLE_SHEETS_CRED_PATH"]
GOOGLE_SHEET_ID: str = os.environ["GOOGLE_SHEET_ID"]

# ===== Cloudflare R2 =====
CF_R2_BUCKET_NAME: str = os.environ["CF_R2_BUCKET_NAME"]
CF_R2_ACCESS_KEY_ID: str = os.environ["CF_R2_ACCESS_KEY_ID"]
CF_R2_SECRET_ACCESS_KEY: str = os.environ["CF_R2_SECRET_ACCESS_KEY"]
CF_R2_ACCOUNT_ID: str = os.environ["CF_R2_ACCOUNT_ID"]
CF_R2_PUBLIC_URL: str = os.environ.get("CF_R2_PUBLIC_URL", "")
