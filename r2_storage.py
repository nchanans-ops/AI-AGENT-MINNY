import boto3
import uuid
import mimetypes
from botocore.config import Config
import config

_s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{config.CF_R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
    aws_access_key_id=config.CF_R2_ACCESS_KEY_ID,
    aws_secret_access_key=config.CF_R2_SECRET_ACCESS_KEY,
    config=Config(signature_version="s3v4"),
    region_name="auto",
)


def upload_image(file_bytes: bytes, filename: str = "") -> str:
    """
    Upload ไฟล์รูปขึ้น R2 คืนค่า public URL
    ถ้า CF_R2_PUBLIC_URL ไม่ได้ตั้ง จะคืน r2.dev URL แบบ default
    """
    ext = ""
    if filename:
        _, ext = filename.rsplit(".", 1) if "." in filename else ("", "jpg")
        ext = ext.lower()
    else:
        ext = "jpg"

    object_key = f"support/{uuid.uuid4().hex}.{ext}"

    content_type, _ = mimetypes.guess_type(f"file.{ext}")
    content_type = content_type or "image/jpeg"

    _s3.put_object(
        Bucket=config.CF_R2_BUCKET_NAME,
        Key=object_key,
        Body=file_bytes,
        ContentType=content_type,
    )

    if config.CF_R2_PUBLIC_URL:
        base = config.CF_R2_PUBLIC_URL.rstrip("/")
        return f"{base}/{object_key}"

    # Fallback: r2.dev public URL (ต้องเปิด Public Access ใน Cloudflare Dashboard)
    return (
        f"https://pub-{config.CF_R2_ACCOUNT_ID}.r2.dev"
        f"/{config.CF_R2_BUCKET_NAME}/{object_key}"
    )
