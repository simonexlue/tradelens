import uuid
from datetime import datetime, timezone
from typing import Optional

from supabase import create_client, Client
from ..core.config import settings

supabase: Optional[Client] = None

def _init_supabase() -> Client:
    # Fail fast if env is missing
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "Supabase not configured: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in Render env."
        )
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

# initialize once at import time
supabase = _init_supabase()
print("Supabase client initialized – DB writes enabled")

def check_trade_belongs_to_user(trade_id: uuid.UUID, user_id: str) -> None:
    res = (
        supabase.table("trades")
        .select("id,user_id")
        .eq("id", str(trade_id))
        .single()
        .execute()
    )
    data = res.data or {}
    if not data:
        raise LookupError("trade_not_found")
    if data["user_id"] != user_id:
        raise PermissionError("trade_not_owned")

def insert_trade(user_id: str, note: str, taken_at: Optional[datetime]) -> uuid.UUID:
    payload = {
        "user_id": user_id,
        "note": note,
        "taken_at": taken_at.isoformat() if taken_at else None,
    }
    res = (
        supabase.table("trades")
        .insert(payload)
        .select("id")
        .single()
        .execute()
    )
    if not res.data or "id" not in res.data:
        raise RuntimeError(f"create_failed: {getattr(res, 'error', None)}")
    return uuid.UUID(res.data["id"])

def insert_image(
    user_id: str,
    trade_id: uuid.UUID,
    key: str,
    content_type: str,
    width: Optional[int],
    height: Optional[int],
) -> dict:
    row = {
        "user_id": user_id,
        "trade_id": str(trade_id),
        "s3_key": key,
        "content_type": content_type,
        "width": width,
        "height": height,
    }
    res = (
        supabase.table("images")
        .insert(row)
        .select("id,s3_key,created_at")
        .single()
        .execute()
    )
    if not res.data:
        raise RuntimeError(f"insert_failed: {getattr(res, 'error', None)}")
    return res.data
