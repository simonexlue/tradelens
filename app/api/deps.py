import uuid
from typing import Optional
from fastapi import Header, HTTPException

def get_current_user_id(x_user_id: Optional[str] = Header(None)) -> str:
    # TEMP for Phase 3; replace with Supabase JWT later.
    if not x_user_id:
        raise HTTPException(status_code=401, detail="x-user-id header required (temp dev auth)")
    try:
        uuid.UUID(x_user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="x-user-id must be a UUID string")
    return x_user_id
