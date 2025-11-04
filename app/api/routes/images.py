from fastapi import APIRouter, Header, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
import boto3, urllib.parse, mimetypes, botocore

from ...services import db
from ...core.config import settings
from ..deps import get_current_user_id

router = APIRouter(prefix="/images", tags=["images"])

s3 = boto3.client("s3", region_name=settings.AWS_REGION)
BUCKET = settings.AWS_S3_BUCKET
if not BUCKET: 
    raise RuntimeError("AWS_S3_BUCKET is missing from env/config")

@router.get("/{key:path}")
def stream_image(
    key: str,
    user_id: str = Depends(get_current_user_id),
    fit: str | None = Query(None)
):
    """
    Streams a private S3 object after verifying ownership in Supabase.
    Frontend sends a URL-encoded key (decode here).
    """
    decoded_key = urllib.parse.unquote(key, encoding="utf-8", errors="strict")

    # Auth: ensure the requesting user owns this image
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
    
    # Fetch from S3 and stream
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