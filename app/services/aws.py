import os, uuid, base64
from datetime import datetime, timezone
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from ..core.config import settings

s3 = boto3.client(
    "s3",
    region_name=settings.AWS_REGION,
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
)

def now_utc(): return datetime.now(timezone.utc)

def gen_key(user_id: str, trade_id: uuid.UUID, ext: str) -> str:
    ts = now_utc().strftime("%Y%m%d-%H%M%S")
    rand = base64.urlsafe_b64encode(os.urandom(4)).decode().rstrip("=")
    return f"u/{user_id}/trades/{trade_id}/{ts}-{rand}.{ext}"

def presign_put(key: str, content_type: str, expires: int = 900) -> str:
    try:
        return s3.generate_presigned_url(
            ClientMethod="put_object",
            Params={"Bucket": settings.AWS_S3_BUCKET, "Key": key, "ContentType": content_type},
            ExpiresIn=expires,
        )
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"presign_failed: {e}")
