import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Path
from ...schemas.trades import CreateTradeBody, CreateTradeResponse
from ...schemas.images import CreateImageBody, CreateImageResponse
from ...services.db import insert_trade, insert_image, check_trade_belongs_to_user
from ..deps import get_current_user_id

router = APIRouter(prefix="/trades", tags=["trades"])

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