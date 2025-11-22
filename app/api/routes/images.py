from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
import boto3, urllib.parse, mimetypes, botocore

from ...services import db
from ...core.config import settings
from ...core.auth import verify_supabase_token

router = APIRouter(prefix="/images", tags=["images"])

if not settings.AWS_S3_BUCKET:
    raise RuntimeError("AWS_S3_BUCKET is missing from env/config")

if not (settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY):
    raise RuntimeError("AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY missing from env/config")

s3 = boto3.client(
    "s3",
    region_name=settings.AWS_REGION,
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
)

BUCKET = settings.AWS_S3_BUCKET


@router.get("/{key:path}")
def stream_image(
    key: str,
    user_id: str = Depends(verify_supabase_token),
    fit: str | None = Query(None),
):
    """
    Streams a private S3 object after verifying ownership in Supabase.
    Frontend sends a URL-encoded key (decode here).
    """
    decoded_key = urllib.parse.unquote(key, encoding="utf-8", errors="strict")

    # Check ownership via DB (images table)
    res = (
        db.supabase.table("images")
        .select("user_id")
        .eq("s3_key", decoded_key)
        .single()
        .execute()
    )
    rec = res.data or {}
    if not rec:
        raise HTTPException(status_code=404, detail="image_not_found")
    if rec["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="forbidden")

    # Fetch and stream from S3
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=decoded_key)
    except botocore.exceptions.ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in ("NoSuchKey", "404"):
            raise HTTPException(status_code=404, detail="not_found")
        raise

    content_type = obj.get("ContentType") or mimetypes.guess_type(decoded_key)[0] or "application/octet-stream"
    etag = obj.get("ETag", "").strip('"')

    headers = {
        "Cache-Control": "private, max-age=60",
        "ETag": etag,
        "Content-Disposition": f'inline; filename="{decoded_key.split("/")[-1]}"',
    }

    return StreamingResponse(obj["Body"].iter_chunks(), media_type=content_type, headers=headers)
