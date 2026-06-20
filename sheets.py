import gspread
from google.oauth2.service_account import Credentials
from datetime import date, timedelta
import re
import config

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# ชื่อคอลัมน์ใน Google Sheet (ปรับให้ตรงกับ Sheet จริง)
COL_SHOP    = "ชื่อร้าน"
COL_CONTACT = "เบอร์/Line"
COL_PACKAGE = "แพ็กเกจ"
COL_START   = "วันเริ่ม"
COL_EXPIRY  = "วันหมดอายุ"
COL_STATUS  = "สถานะ"

# mapping ชื่อเดือนภาษาไทย → เลขเดือน
THAI_MONTHS = {
    "มกราคม": 1,  "ม.ค.": 1,
    "กุมภาพันธ์": 2, "ก.พ.": 2,
    "มีนาคม": 3,  "มี.ค.": 3,
    "เมษายน": 4,  "เม.ย.": 4,
    "พฤษภาคม": 5, "พ.ค.": 5,
    "มิถุนายน": 6, "มิ.ย.": 6,
    "กรกฎาคม": 7, "ก.ค.": 7,
    "สิงหาคม": 8, "ส.ค.": 8,
    "กันยายน": 9, "ก.ย.": 9,
    "ตุลาคม": 10, "ต.ค.": 10,
    "พฤศจิกายน": 11, "พ.ย.": 11,
    "ธันวาคม": 12, "ธ.ค.": 12,
}


def _get_sheet():
    creds = Credentials.from_service_account_file(
        config.GOOGLE_SHEETS_CRED_PATH, scopes=SCOPES
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(config.GOOGLE_SHEET_ID)
    return sh.sheet1


def _parse_date(value: str) -> date | None:
    """แปลง string หลายรูปแบบเป็น date"""
    value = value.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return date.fromisoformat(
                __import__("datetime").datetime.strptime(value, fmt).strftime("%Y-%m-%d")
            )
        except ValueError:
            continue
    return None


def _get_rows() -> list[dict]:
    """ดึงข้อมูลทุกแถวจาก Sheet"""
    sheet = _get_sheet()
    return sheet.get_all_records()


def get_expiring_next_n_days(n: int = 7) -> list[dict]:
    """ลูกค้าที่หมดอายุใน n วันข้างหน้า (รวมวันนี้)"""
    today = date.today()
    cutoff = today + timedelta(days=n)
    results = []
    for row in _get_rows():
        exp = _parse_date(str(row.get(COL_EXPIRY, "")))
        if exp and today <= exp <= cutoff:
            results.append({
                "shop": row.get(COL_SHOP, ""),
                "contact": row.get(COL_CONTACT, ""),
                "package": row.get(COL_PACKAGE, ""),
                "expiry": exp.strftime("%d/%m/%Y"),
                "status": row.get(COL_STATUS, ""),
            })
    results.sort(key=lambda r: r["expiry"])
    return results


def get_expiring_this_month() -> list[dict]:
    """ลูกค้าที่หมดอายุเดือนนี้"""
    today = date.today()
    return get_expiring_by_month(today.year, today.month)


def get_expiring_by_month(year: int, month: int) -> list[dict]:
    """ลูกค้าที่หมดอายุในเดือนที่ระบุ"""
    results = []
    for row in _get_rows():
        exp = _parse_date(str(row.get(COL_EXPIRY, "")))
        if exp and exp.year == year and exp.month == month:
            results.append({
                "shop": row.get(COL_SHOP, ""),
                "contact": row.get(COL_CONTACT, ""),
                "package": row.get(COL_PACKAGE, ""),
                "expiry": exp.strftime("%d/%m/%Y"),
                "status": row.get(COL_STATUS, ""),
            })
    results.sort(key=lambda r: r["expiry"])
    return results


def parse_expiry_query(text: str) -> list[dict]:
    """
    วิเคราะห์คำถาม แล้วคืนรายการหมดอายุที่เกี่ยวข้อง
    รองรับ:
      - "เร็วๆ นี้" / "7 วัน" → 7 วันข้างหน้า
      - "เดือนนี้"             → เดือนปัจจุบัน
      - "เดือน [ชื่อเดือน]"   → เดือนที่ระบุ
    """
    text_lower = text.lower()

    # เดือนที่ระบุชื่อ
    for thai_name, month_num in THAI_MONTHS.items():
        if thai_name in text:
            today = date.today()
            year = today.year
            # ถ้าเดือนที่ระบุผ่านไปแล้วในปีนี้ → ให้เดาเป็นปีหน้า
            if month_num < today.month:
                year += 1
            return get_expiring_by_month(year, month_num)

    # เดือนนี้
    if "เดือนนี้" in text:
        return get_expiring_this_month()

    # ค่าเริ่มต้น: 7 วันข้างหน้า (เร็วๆ นี้, วันนี้, ฯลฯ)
    return get_expiring_next_n_days(7)


def format_expiry_list(rows: list[dict], label: str = "") -> str:
    """จัดรูปแบบผลลัพธ์เป็น text สำหรับส่งใน Telegram"""
    if not rows:
        header = f"ช่วง{label}ไม่มีลูกค้าหมดอายุเลย 🎉" if label else "ไม่มีลูกค้าหมดอายุในช่วงนี้ 🎉"
        return header

    lines = [f"พบลูกค้าหมดอายุ {len(rows)} ราย:\n"]
    for r in rows:
        status_tag = f" ({r['status']})" if r["status"] else ""
        lines.append(
            f"🔴 {r['shop']}\n"
            f"   แพ็กเกจ: {r['package']}\n"
            f"   หมดอายุ: {r['expiry']}{status_tag}\n"
            f"   ติดต่อ: {r['contact']}"
        )
    return "\n\n".join(lines)
