import gspread
from google.oauth2.service_account import Credentials
from datetime import date, timedelta
import re
import config

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# ชื่อ sheet ที่ใช้ติดตามหมดอายุ
SHEET_NAME = "หมดอายุ VIP"

# ชื่อ column ใน Google Sheet (ตรงกับ Sheet จริง)
COL_SHOP    = "ชื่อกลุ่ม"
COL_CONTACT = "เบอร์โทรศัพท์"
COL_PACKAGE = "แพ็กเกจ"
COL_EXPIRY  = "วันหมดอายุ"
COL_STATUS  = "สถานะ"

# mapping เดือนไทย → เลขเดือน
THAI_MONTH_SHORT = {
    "ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4,
    "พ.ค.": 5, "มิ.ย.": 6, "ก.ค.": 7,  "ส.ค.": 8,
    "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12,
}

THAI_MONTH_FULL = {
    "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3,   "เมษายน": 4,
    "พฤษภาคม": 5, "มิถุนายน": 6,  "กรกฎาคม": 7,  "สิงหาคม": 8,
    "กันยายน": 9, "ตุลาคม": 10,   "พฤศจิกายน": 11, "ธันวาคม": 12,
}


def _get_sheet():
    creds = Credentials.from_service_account_file(
        config.GOOGLE_SHEETS_CRED_PATH, scopes=SCOPES
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(config.GOOGLE_SHEET_ID)
    try:
        return sh.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        return sh.sheet1


def _parse_thai_date(value: str) -> date | None:
    """
    แปลงรูปแบบวันที่ไทยหลายแบบ → date
    รองรับ:
      - "22 ต.ค. 2025, 10:08"
      - "22 ต.ค. 2025"
      - "22/10/2025", "22-10-2025", "2025-10-22"
    """
    value = value.strip()
    if not value:
        return None

    # รูปแบบ "DD ม.ม. YYYY" หรือ "DD ม.ม. YYYY, HH:MM"
    for th, num in {**THAI_MONTH_SHORT, **THAI_MONTH_FULL}.items():
        if th in value:
            # ดึงตัวเลขวันและปี
            nums = re.findall(r"\d+", value)
            if len(nums) >= 2:
                day = int(nums[0])
                year = int(nums[1]) if int(nums[1]) > 100 else int(nums[1]) + 2000
                try:
                    return date(year, num, day)
                except ValueError:
                    return None

    # รูปแบบตัวเลขล้วน
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            import datetime
            return datetime.datetime.strptime(value.split(",")[0].strip(), fmt).date()
        except ValueError:
            continue

    return None


def _get_rows() -> list[dict]:
    sheet = _get_sheet()
    return sheet.get_all_records()


def get_expiring_next_n_days(n: int = 7) -> list[dict]:
    today = date.today()
    cutoff = today + timedelta(days=n)
    results = []
    for row in _get_rows():
        exp = _parse_thai_date(str(row.get(COL_EXPIRY, "")))
        if exp and today <= exp <= cutoff:
            results.append({
                "shop":    row.get(COL_SHOP, ""),
                "contact": row.get(COL_CONTACT, ""),
                "package": row.get(COL_PACKAGE, ""),
                "expiry":  exp.strftime("%d/%m/%Y"),
                "status":  row.get(COL_STATUS, ""),
            })
    results.sort(key=lambda r: r["expiry"])
    return results


def get_expiring_this_month() -> list[dict]:
    today = date.today()
    return get_expiring_by_month(today.year, today.month)


def get_expiring_by_month(year: int, month: int) -> list[dict]:
    results = []
    for row in _get_rows():
        exp = _parse_thai_date(str(row.get(COL_EXPIRY, "")))
        if exp and exp.year == year and exp.month == month:
            results.append({
                "shop":    row.get(COL_SHOP, ""),
                "contact": row.get(COL_CONTACT, ""),
                "package": row.get(COL_PACKAGE, ""),
                "expiry":  exp.strftime("%d/%m/%Y"),
                "status":  row.get(COL_STATUS, ""),
            })
    results.sort(key=lambda r: r["expiry"])
    return results


def parse_expiry_query(text: str) -> list[dict]:
    """วิเคราะห์คำถามแล้วคืนรายการหมดอายุที่ตรง"""
    # เดือนที่ระบุชื่อ
    for th_name, month_num in {**THAI_MONTH_FULL, **THAI_MONTH_SHORT}.items():
        if th_name in text:
            today = date.today()
            year = today.year
            if month_num < today.month:
                year += 1
            return get_expiring_by_month(year, month_num)

    if "เดือนนี้" in text:
        return get_expiring_this_month()

    # default: 7 วันข้างหน้า
    return get_expiring_next_n_days(7)


def format_expiry_list(rows: list[dict]) -> str:
    if not rows:
        return "ไม่มีลูกค้าหมดอายุในช่วงนี้ 🎉"

    lines = [f"พบลูกค้าหมดอายุ {len(rows)} ราย:\n"]
    for r in rows:
        status_tag = f" ({r['status']})" if r["status"] else ""
        pkg_line = f"\n   แพ็กเกจ: {r['package']}" if r["package"] else ""
        lines.append(
            f"🔴 {r['shop']}{pkg_line}\n"
            f"   หมดอายุ: {r['expiry']}{status_tag}"
        )
    return "\n\n".join(lines)
