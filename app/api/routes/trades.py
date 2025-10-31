import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from ...schemas.trades import CreateTradeBody, CreateTradeResponse
from ...schemas.images import CreateImageBody, CreateImageResponse
from ...services.db import (
    insert_trade, 
    insert_image, 
    check_trade_belongs_to_user, 
    fetch_trades_for_user, 
    fetch_trade_with_images
    )
from ..deps import get_current_user_id
import base64
import json
from typing import Any, Dict, List, Optional

router = APIRouter(prefix="/trades", tags=["trades"])


#----------------------------------------- HELPERS -----------------------------------------

def _encode_cursor(created_at_iso: str, trade_id: str) -> str:
    payload = {"created_at": created_at_iso, "id": trade_id}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()

def _decode_cursor(cursor: str) -> Dict[str, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        payload = json.loads(raw)
        if not payload.get("created_at") or not payload.get("id"):
            raise ValueError("cursor missing fields")
        return payload
    except Exception as e:
        raise HTTPException(status_code=400, detail="invalid_cursor") from e

#----------------------------------------- GET -----------------------------------------

@router.get("/")
def list_trades(
    limit: int = Query(12, ge=1, le=50),
    cursor: Optional[str] = Query(None),
    user_id: str = Depends(get_current_user_id),
):
    after = _decode_cursor(cursor) if cursor else None
    items = fetch_trades_for_user(user_id=user_id, limit=limit, after=after)

    # Build nextCursor if we returned a full page
    next_cursor = None
    if len(items) == limit:
        tail = items[-1]
        next_cursor = _encode_cursor(tail["created_at"], str(tail["id"]))

    # shape expected by frontend:
    # { items: [{id, note, created_at, images: [{s3_key, width, height}], image_count}], nextCursor}
    return {"items": items, "nextCursor": next_cursor}

# mirror without trailing slash
@router.get("", include_in_schema=False)
def list_trades_noslash(
    limit: int = Query(12, ge=1, le=50),
    cursor: Optional[str] = Query(None),
    user_id: str = Depends(get_current_user_id),
):
    return list_trades(limit=limit, cursor=cursor, user_id=user_id)


@router.get("/{trade_id}")
def get_trade(
    trade_id: uuid.UUID = Path(...),
    user_id: str = Depends(get_current_user_id),
):
    # raise 404 if not owned / not found
    trade = fetch_trade_with_images(user_id=user_id, trade_id=trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="trade_not_found")
    return trade

#----------------------------------------- POST -----------------------------------------

@router.post("/", response_model=CreateTradeResponse)
def create_trade(body: CreateTradeBody, user_id: str = Depends(get_current_user_id)):
    tid = insert_trade(user_id, body.note or "", body.takenAt)
    return CreateTradeResponse(tradeId=tid)

@router.post("/{trade_id}/images", response_model=CreateImageResponse, status_code=201)
def create_image(
    body: CreateImageBody,
    trade_id: uuid.UUID = Path(...),
    user_id: str = Depends(get_current_user_id),
):
    check_trade_belongs_to_user(trade_id, user_id)

    expected_prefix = f"u/{user_id}/trades/{trade_id}/"
    if not body.key.startswith(expected_prefix):
        raise HTTPException(status_code=400, detail="invalid_key_prefix")

    row = insert_image(
        user_id=user_id,
        trade_id=trade_id,
        key=body.key,
        content_type=body.contentType,
        width=body.width,
        height=body.height,
    )

    created_raw = row.get("created_at") or row.get("inserted_at")
    if not created_raw:
        raise HTTPException(status_code=500, detail="missing_created_at")

    # normalize for fromisoformat()
    created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))

    return CreateImageResponse(
        imageId=uuid.UUID(row["id"]),
        s3Key=row["s3_key"],
        createdAt=created_at,
    )

# mirror route WITH trailing slash to avoid Starlette auto-redirects
@router.post("/{trade_id}/images/", include_in_schema=False, status_code=201)
def create_image_trailing(
    body: CreateImageBody,
    trade_id: uuid.UUID = Path(...),
    user_id: str = Depends(get_current_user_id),
):
    return create_image(body, trade_id, user_id)