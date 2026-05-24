"""Cloudflare R2 (S3-compatible) media upload utility."""
import asyncio
import mimetypes
import uuid
from functools import partial

from app.config import settings

ALLOWED_MIME_TYPES: frozenset[str] = frozenset({
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/svg+xml",
})

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def is_r2_configured() -> bool:
    return bool(
        settings.R2_ACCOUNT_ID
        and settings.R2_ACCESS_KEY_ID
        and settings.R2_SECRET_ACCESS_KEY
        and settings.R2_BUCKET_NAME
        and settings.R2_PUBLIC_URL
    )


def _upload_sync(data: bytes, content_type: str, key: str) -> None:
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )
    client.put_object(
        Bucket=settings.R2_BUCKET_NAME,
        Key=key,
        Body=data,
        ContentType=content_type,
        CacheControl="public, max-age=31536000",
    )


async def upload_to_r2(data: bytes, content_type: str, folder: str = "media") -> str:
    """Upload bytes to R2 and return the public CDN URL."""
    ext = mimetypes.guess_extension(content_type) or ".bin"
    # mimetypes.guess_extension returns ".jpe" for image/jpeg on some systems
    if content_type == "image/jpeg":
        ext = ".jpg"
    elif content_type == "image/svg+xml":
        ext = ".svg"

    key = f"{folder}/{uuid.uuid4().hex}{ext}"
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, partial(_upload_sync, data, content_type, key))
    return f"{settings.R2_PUBLIC_URL.rstrip('/')}/{key}"
