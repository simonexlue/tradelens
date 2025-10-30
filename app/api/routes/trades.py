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

@router.post("/{trade_id}/images", response_model=CreateImageResponse)
def create_image(
    body: CreateImageBody,
    trade_id: uuid.UUID = Path(...),
    user_id: str = Depends(get_current_user_id),
):
    try:
        check_trade_belongs_to_user(trade_id, user_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="trade_not_found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="trade_not_owned")

    expected_prefix = f"u/{user_id}/trades/{trade_id}/"
    if not body.key.startswith(expected_prefix):
        raise HTTPException(status_code=400, detail="invalid_key_prefix")

    row = insert_image(user_id, trade_id, body.key, body.contentType, body.width, body.height)
    return CreateImageResponse(
        imageId=uuid.UUID(row["id"]),
        s3Key=row["s3_key"],
        createdAt=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
    )
