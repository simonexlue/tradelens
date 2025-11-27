import os, uuid, base64
from datetime import datetime, timezone
import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from ..core.config import settings

region = settings.AWS_REGION

s3 = boto3.client(
    "s3",
    region_name=region,
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    endpoint_url=f"https://s3.{region}.amazonaws.com",  # force regional endpoint
    config=Config(
        signature_version="s3v4",
        s3={"addressing_style": "virtual"}  # <bucket>.s3.<region>.amazonaws.com
    ),
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

def delete_object(key: str) -> None:
    """
    Delete an object from S3 by key.
    """
    try:
        s3.delete_object(Bucket=settings.AWS_S3_BUCKET, Key=key)
    except (BotoCoreError, ClientError) as e:
        print(f"Failed to delete S3 object {key}: {e}")

def get_object_bytes(key: str) -> bytes:
    """"
    Download an object from S3 and return its raw bytes.
    """
    try: 
        res = s3.get_object(Bucket=settings.AWS_S3_BUCKET, Key=key)
        return res["Body"].read()
    except(BotoCoreError, ClientError) as e:
        raise RuntimeError(f"download_failed: {e}")