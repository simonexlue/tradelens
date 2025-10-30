import uuid
from datetime import datetime, timezone
from typing import Optional

from ..core.config import settings

supabase = None
if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY:
    try:
        from supabase import create_client
        supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    except Exception as e:
        print("Warning: Supabase init failed:", e)
        supabase = None

def check_trade_belongs_to_user(trade_id: uuid.UUID, user_id: str) -> None:
    if supabase is None:  # dev mode
        return
    res = supabase.table("trades").select("id,user_id").eq("id", str(trade_id)).single().execute()
    data = res.data or {}
    if not data:
        raise LookupError("trade_not_found")
    if data["user_id"] != user_id:
        raise PermissionError("trade_not_owned")

def insert_trade(user_id: str, note: str, taken_at: Optional[datetime]) -> uuid.UUID:
    if supabase is None:
        return uuid.uuid4()
    payload = {"user_id": user_id, "note": note, "taken_at": taken_at.isoformat() if taken_at else None}
    res = supabase.table("trades").insert(payload).select("id").single().execute()
    if not res.data:
        raise RuntimeError("create_failed")
    return uuid.UUID(res.data["id"])

def insert_image(user_id: str, trade_id: uuid.UUID, key: str, content_type: str,
                 width: Optional[int], height: Optional[int]) -> dict:
    if supabase is None:
        return {"id": str(uuid.uuid4()), "s3_key": key, "created_at": datetime.now(timezone.utc).isoformat()}
    row = {
        "user_id": user_id,
        "trade_id": str(trade_id),
        "s3_key": key,
        "content_type": content_type,
        "width": width,
        "height": height,
    }
    res = supabase.table("images").insert(row).select("id,s3_key,created_at").single().execute()
    if not res.data:
        raise RuntimeError("insert_failed")
    return res.data
