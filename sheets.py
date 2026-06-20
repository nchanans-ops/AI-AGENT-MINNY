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
    # แบบไม่มีจุด
    "มค": 1, "กพ": 2, "มีค": 3, "เมย": 4,
    "พค": 5, "มิย": 6, "กค": 7,  "สค": 8,
    "กย": 9, "ตค": 10, "พย": 11, "ธค": 12,
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
    """วิเคราะห์คำถามแล้วคืนรายการหมดอายุที่ตรง
    รองรับ: ชื่อเดือนทุกรูปแบบ, เลขเดือน, สัปดาห์หน้า, เดือนหน้า ฯลฯ
    """
    today = date.today()

    # ── สัปดาห์หน้า / อาทิตย์หน้า ──
    if any(w in text for w in ["สัปดาห์หน้า", "อาทิตย์หน้า"]):
        return get_expiring_next_n_days(7)

    # ── เดือนหน้า ──
    if "เดือนหน้า" in text:
        nm = today.month % 12 + 1
        ny = today.year + (1 if today.month == 12 else 0)
        return get_expiring_by_month(ny, nm)

    # ── เดือนนี้ ──
    if "เดือนนี้" in text:
        return get_expiring_this_month()

    # ── เลขเดือน: "เดือน 7", "เดือนที่7", "เดือน7" ──
    m = re.search(r"เดือน(?:ที่)?\s*(\d{1,2})", text)
    if m:
        mn = int(m.group(1))
        if 1 <= mn <= 12:
            yr = today.year + (1 if mn < today.month else 0)
            return get_expiring_by_month(yr, mn)

    # ── ชื่อเดือนไทย (เรียงยาว→สั้น กัน false positive) ──
    all_months = {**THAI_MONTH_FULL, **THAI_MONTH_SHORT}
    for th_name in sorted(all_months, key=len, reverse=True):
        if th_name in text:
            mn = all_months[th_name]
            yr = today.year + (1 if mn < today.month else 0)
            return get_expiring_by_month(yr, mn)

    # ── default: 7 วันข้างหน้า ──
    return get_expiring_next_n_days(7)


def find_customer_expiry(name: str) -> dict | None:
    """ค้นหาลูกค้าจากชื่อ (partial match) แล้วคืนข้อมูลหมดอายุ"""
    name_lower = name.lower().strip()
    if not name_lower:
        return None
    for row in _get_rows():
        shop = str(row.get(COL_SHOP, "")).lower()
        if name_lower in shop:
            exp = _parse_thai_date(str(row.get(COL_EXPIRY, "")))
            return {
                "shop":   row.get(COL_SHOP, ""),
                "expiry": exp.strftime("%d/%m/%Y") if exp else "",
                "status": row.get(COL_STATUS, ""),
            }
    return None


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
