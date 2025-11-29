import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from ...utils.sessions import infer_session_from_entry
from ...schemas.trades import CreateTradeBody, CreateTradeResponse, UpdateTradeBody
from ...schemas.images import CreateImageBody, CreateImageResponse
from ...schemas.analysis import AnalysisResponse, AnalyzeTradeBody
from ...services.db import (
    insert_trade,
    insert_image,
    check_trade_belongs_to_user,
    fetch_trades_for_user,
    fetch_trade_with_images,
    get_image_for_trade,
    delete_image_record,
    insert_trade_analysis,
    delete_trade_record,
    update_trade_fields,
    fetch_user_strategies,
)
from ...core.auth import verify_supabase_token
from ...services.aws import delete_object, get_object_bytes
from ...services.ai_analysis import run_trade_analysis

import base64
import json
from typing import Dict, Optional

router = APIRouter(prefix="/trades", tags=["trades"])

# ----------------------------------------- HELPERS -----------------------------------------
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
    
def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        # assume frontend sends UTC if naive
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ----------------------------------------- GET -----------------------------------------
@router.get("/")
def list_trades(
    limit: int = Query(12, ge=1, le=50),
    cursor: Optional[str] = Query(None),
    user_id: str = Depends(verify_supabase_token),
):
    after = _decode_cursor(cursor) if cursor else None
    items = fetch_trades_for_user(user_id=user_id, limit=limit, after=after)

    next_cursor = None
    if len(items) == limit:
        tail = items[-1]
        next_cursor = _encode_cursor(tail["created_at"], str(tail["id"]))

    return {"items": items, "nextCursor": next_cursor}

@router.get("", include_in_schema=False)
def list_trades_noslash(
    limit: int = Query(12, ge=1, le=50),
    cursor: Optional[str] = Query(None),
    user_id: str = Depends(verify_supabase_token),
):
    return list_trades(limit=limit, cursor=cursor, user_id=user_id)

@router.get("/{trade_id}")
def get_trade(
    trade_id: uuid.UUID = Path(...),
    user_id: str = Depends(verify_supabase_token),
):
    trade = fetch_trade_with_images(user_id=user_id, trade_id=trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="trade_not_found")
    return trade

@router.get("/strategies")
def list_strategies(
    user_id: str = Depends(verify_supabase_token),
):
    """"
    Return distinct strategy labels for this user to power the strategy dropdown.
    """
    strategies = fetch_user_strategies(user_id=user_id)
    return {"strategies": strategies}

# ----------------------------------------- POST -----------------------------------------
@router.post("/", response_model=CreateTradeResponse)
def create_trade(body: CreateTradeBody, user_id: str = Depends(verify_supabase_token)):
    # 1) Determine taken_at
    if body.takenAt is not None:
        taken_at = _ensure_aware(body.takenAt)
    else:
        # fallback: use "now" as entry time
        taken_at = datetime.now(timezone.utc)

    # 2) Ensure exit_at is aware if provided
    exit_at = _ensure_aware(body.exitAt) if body.exitAt is not None else None

    # 3) Infer session from entry time
    try:
        session = infer_session_from_entry(taken_at)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 4) Insert trade with all fields
    tid = insert_trade(
        user_id=user_id,
        note=body.note or "",
        taken_at=taken_at,
        exit_at=exit_at,
        outcome=body.outcome,
        r_multiple=body.rMultiple,
        strategy=body.strategy,
        session=session,
        mistakes=body.mistakes,
    )

    return CreateTradeResponse(tradeId=tid)


@router.post("/{trade_id}/images", response_model=CreateImageResponse, status_code=201)
def create_image(
    body: CreateImageBody,
    trade_id: uuid.UUID = Path(...),
    user_id: str = Depends(verify_supabase_token),
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

    created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))

    return CreateImageResponse(
        imageId=uuid.UUID(row["id"]),
        s3Key=row["s3_key"],
        createdAt=created_at,
    )

@router.post("/{trade_id}/images/", include_in_schema=False, status_code=201)
def create_image_trailing(
    body: CreateImageBody,
    trade_id: uuid.UUID = Path(...),
    user_id: str = Depends(verify_supabase_token),
):
    return create_image(body, trade_id, user_id)

# ----------------------------------------- PUT -----------------------------------------
@router.put("/{trade_id}")
def update_trade(
    body: UpdateTradeBody,
    trade_id: uuid.UUID = Path(...),
    user_id: str = Depends(verify_supabase_token),
):
    check_trade_belongs_to_user(trade_id, user_id)

    taken_at = None
    session = None
    exit_at = None

    if body.takenAt is not None:
        taken_at = _ensure_aware(body.takenAt)
        try:
            session = infer_session_from_entry(taken_at)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    if body.exitAt is not None:
        exit_at = _ensure_aware(body.exitAt)

    # Send only non-None values to DB
    update_trade_fields(
        user_id=user_id,
        trade_id=trade_id,
        note=body.note,
        taken_at=taken_at,
        exit_at=exit_at,
        outcome=body.outcome,
        r_multiple=body.rMultiple,
        strategy=body.strategy,
        session=session,
        mistakes=body.mistakes,
    )

    trade = fetch_trade_with_images(user_id=user_id, trade_id=trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="trade_not_found")
    return trade


@router.put("/{trade_id}/", include_in_schema=False)
def update_trade_trailing(
    body: UpdateTradeBody,
    trade_id: uuid.UUID = Path(...),
    user_id: str = Depends(verify_supabase_token),
):
    return update_trade(body=body, trade_id=trade_id, user_id=user_id)


# ----------------------------------------- DELETE IMAGE -----------------------------------------
@router.delete("/{trade_id}/images/{image_id}", status_code=204)
def delete_image(
    trade_id: uuid.UUID = Path(...),
    image_id: uuid.UUID = Path(...),
    user_id: str = Depends(verify_supabase_token),
):
    # Ensure the trade belongs to the user
    check_trade_belongs_to_user(trade_id, user_id)

    # Fetch image row + ownership
    try:
        img_row = get_image_for_trade(
            user_id=user_id,
            trade_id=trade_id,
            image_id=image_id,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="image_not_found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="forbidden")

    s3_key = img_row["s3_key"]

    # 1) Delete from DB
    delete_image_record(image_id=image_id)

    # 2) Delete from S3
    try:
        delete_object(s3_key)
    except Exception as e:
        # Log but don't block user
        print("Failed to delete S3 object", s3_key, e)

    return

# ----------------------------------------- DELETE TRADE -----------------------------------------
@router.delete("/{trade_id}", status_code=204)
def delete_trade(
    trade_id: uuid.UUID = Path(...),
    user_id: str = Depends(verify_supabase_token),
):
    """
    Delete a trade and all associated images (DB + S3).
    """

    # Ensure trade belongs to this user
    check_trade_belongs_to_user(trade_id, user_id)

    # Fetch trade + images for deletion
    trade = fetch_trade_with_images(user_id=user_id, trade_id=trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="trade_not_found")
    
    # 1) Delete all images (DB + S3)
    for img in trade.get("images", []):
        img_id_str = img.get("id")
        s3_key = img.get("s3_key")

        if not img_id_str or not s3_key:
            continue

        try:
            delete_image_record(image_id=uuid.UUID(img_id_str))
        except Exception as e:
            print("Failed to delete image record", img_id_str, e)

        try:
            delete_object(s3_key)
        except Exception as e:
            print("Failed to delete S3 object", s3_key, e)

    # 2) Delete the trade itself 
    try: 
        delete_trade_record(user_id=user_id, trade_id=trade_id)
    except Exception as e:
        print("Failed to delete trade record", trade_id, e)
        raise HTTPException(status_code=500, detail="delete_trade_failed")
    
    return


# ----------------------------------------- TRADE ANALYSIS -----------------------------------------

@router.post("/{trade_id}/analyze", response_model=AnalysisResponse)
async def analyze_trade(
    body: AnalyzeTradeBody,
    trade_id: uuid.UUID = Path(...),
    user_id: str = Depends(verify_supabase_token),
): 
    """
    Generate AI analysis for a trade using a specific screenshot chosen by the user.
    """

    # 1. Ensure trade belongs to the user
    check_trade_belongs_to_user(trade_id, user_id)

    #2 Fetch specific image for the trade 
    try:
        img_row = get_image_for_trade(
            user_id=user_id,
            trade_id=trade_id,
            image_id=body.imageId,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="image_not_found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="forbidden")
    
    s3_key = img_row["s3_key"]

    # 3. Download image bytes from S3
    try: 
        image_bytes = get_object_bytes(s3_key)
    except Exception as e:
        print("Failed to download image from S3", s3_key, e)
        raise HTTPException(status_code=500, detail="image_download_failed")
    
    # 4. Load trade to get note
    trade = fetch_trade_with_images(user_id=user_id, trade_id=trade_id)
    if not trade: 
        raise HTTPException(status_code=404, detail="trade_not_found")
    
    note = trade.get("note") or None

    mime_type = "image/png"

    # 5. Run AI analysis on selected image
    try: 
        analysis = await run_trade_analysis(
            image_bytes=image_bytes,
            mime_type=mime_type,
            user_note=note,
        )
    except Exception as e:
        # dev logging
        print("AI analysis failed", repr(e))
        # surface the actual error for now (dev only)
        raise HTTPException(
            status_code=500,
            detail=f"ai_analysis_failed: {e!r}",
        )
    
    # 6. Persist analysis
    try: 
        row = insert_trade_analysis(
            user_id=user_id,
            trade_id=trade_id,
            what_happened=analysis["what_happened"],
            why_result=analysis["why_result"],
            tips=analysis["tips"],
            model="gpt-4o-mini",
        )
    except Exception as e:
        print("Failed to insert trade analysis", e)
        raise HTTPException(status_code=500, detail="analysis_persist_failed")
    
    # 7) Return structured analysis (what frontend expects)
    return {
        "what_happened": row["what_happened"],
        "why_result": row["why_result"],
        "tips": row["tips"],
    }