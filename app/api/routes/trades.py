import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from ...utils.sessions import infer_session_from_entry
from ...schemas.trades import CreateTradeBody, CreateTradeResponse, UpdateTradeBody, CsvImportRequest, CsvImportResult, CsvImportRow
from ...schemas.images import CreateImageBody, CreateImageResponse
from ...schemas.analysis import AnalysisResponse, AnalyzeTradeBody
from ...schemas.calendar import CalendarResponse
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
    fetch_trade_filters,
    fetch_trade_calendar,
    trade_exists_for_user,
    ensure_account_belongs_to_user,
)
from ...core.auth import verify_supabase_token
from ...services.aws import delete_object, get_object_bytes
from ...services.ai_analysis import run_trade_analysis

import base64
import json
from typing import Dict, Optional, List

router = APIRouter(prefix="/trades", tags=["trades"])

# ----------------------------------------- HELPERS -----------------------------------------
def _encode_cursor(sort_at_iso: str, trade_id: str) -> str:
    payload = {"sort_at": sort_at_iso, "id": trade_id}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()

def _decode_cursor(cursor: str) -> Dict[str, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        payload = json.loads(raw)
        if not payload.get("sort_at") or not payload.get("id"):
            raise ValueError("cursor missing fields")
        return payload
    except Exception as e:
        raise HTTPException(status_code=400, detail="invalid_cursor") from e
    
def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        # assume frontend sends UTC if naive
        return dt.replace(tzinfo=timezone.utc)
    return dt

def _parse_csv_timestamp(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None

    s = s.strip()

    # 1) Try Topstep-style: "10/22/2025 00:20:00 -07:00"
    try:
        dt_with_tz = datetime.strptime(s, "%m/%d/%Y %H:%M:%S %z")
        utc_dt = dt_with_tz.astimezone(timezone.utc)
        return utc_dt
    except ValueError:
        # not Topstep format, fall through to Tradovate
        pass

    # 2) Fallback: Tradovate-style without offset: "12/09/2025 11:50:16"
    dt_naive = datetime.strptime(s, "%m/%d/%Y %H:%M:%S")

    # Treat as America/Vancouver local (PST = UTC-8 in December)
    local_tz = timezone(timedelta(hours=-8))
    local_dt = dt_naive.replace(tzinfo=local_tz)
    utc_dt = local_dt.astimezone(timezone.utc)

    print(
        f"CSV timestamp (Tradovate) raw={s!r} -> local={local_dt.isoformat()} -> utc={utc_dt.isoformat()}"
    )

    return utc_dt

# ----------------------------------------- GET -----------------------------------------
@router.get("/")
def list_trades(
    limit: int = Query(12, ge=1, le=50),
    cursor: Optional[str] = Query(None),
    outcome: List[str] = Query(default=[]),
    session: List[str] = Query(default=[]),
    strategy: List[str] = Query(default=[]),
    symbol: List[str] = Query(default=[]),
    user_id: str = Depends(verify_supabase_token),
):
    after = _decode_cursor(cursor) if cursor else None

    filters = {
        "outcome": outcome or [],
        "session": session or [],
        "strategy" : strategy or [],
        "symbol" : symbol or [],
    }
    items = fetch_trades_for_user(user_id=user_id, limit=limit, after=after, filters=filters)

    next_cursor = None
    if len(items) == limit:
        tail = items[-1]
        sort_at = tail.get("sort_at")
        if sort_at:
            next_cursor = _encode_cursor(sort_at, str(tail["id"]))

    return {"items": items, "nextCursor": next_cursor}

@router.get("", include_in_schema=False)
def list_trades_noslash(
    limit: int = Query(12, ge=1, le=50),
    cursor: Optional[str] = Query(None),
    outcome: List[str] = Query(default=[]),
    session: List[str] = Query(default=[]),
    strategy: List[str] = Query(default=[]),
    symbol: List[str] = Query(default=[]),
    user_id: str = Depends(verify_supabase_token),
):
    return list_trades(
        limit=limit,
        cursor=cursor,
        outcome=outcome,
        session=session,
        strategy=strategy,
        symbol=symbol,
        user_id=user_id,
    )


@router.get("/strategies")
def list_strategies(
    user_id: str = Depends(verify_supabase_token),
):
    """"
    Return distinct strategy labels for this user to power the strategy dropdown.
    """
    strategies = fetch_user_strategies(user_id=user_id)
    return {"strategies": strategies}

@router.get("/filters")
def list_trade_filters(
    user_id: str = Depends(verify_supabase_token)
):
    """"
    Return distinct filter options for this user's trades
    """
    filters = fetch_trade_filters(user_id=user_id)
    return filters 

@router.get("/calendar", response_model=CalendarResponse)
def get_trade_calendar(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    outcome: List[str] = Query(default=[]),
    session: List[str] = Query(default=[]),
    strategy: List[str] = Query(default=[]),
    symbol: List[str] = Query(default=[]),
    user_id: str = Depends(verify_supabase_token),
):
    """
    Per-day P&L and trade count for a given month.
    Same filter semantics as list_trades.
    """
    filters = {
        "outcome": outcome or [],
        "session": session or [],
        "strategy": strategy or [],
        "symbol": symbol or [],
    }

    days = fetch_trade_calendar(
        user_id=user_id,
        year=year,
        month=month,
        filters=filters,
    )

    return CalendarResponse(days=days)

@router.get("/{trade_id}")
def get_trade(
    trade_id: uuid.UUID = Path(...),
    user_id: str = Depends(verify_supabase_token),
):
    trade = fetch_trade_with_images(user_id=user_id, trade_id=trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="trade_not_found")
    return trade

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
        strategies=body.strategies,
        session=session,
        mistakes=body.mistakes,
        side=body.side,
        entry_price=body.entryPrice,
        exit_price=body.exitPrice,
        contracts=body.contracts,
        pnl=body.pnl,
        symbol=body.symbol,
        account_id=str(body.accountId) if body.accountId is not None else None,
    )

    return CreateTradeResponse(tradeId=tid)

@router.post("/import-csv", response_model=CsvImportResult)
async def import_trades_csv(
    payload: CsvImportRequest,
    user_id: str = Depends(verify_supabase_token),
):
    inserted = 0
    failed = 0
    duplicates = 0

    # normalize & validate the account for this user (if provided)
    account_id = str(payload.accountId) if payload.accountId else None
    ensure_account_belongs_to_user(account_id=account_id, user_id=user_id)


    # Avoid duplicates within this CSV (optional but fine to keep)
    seen_keys = set()

    for row in payload.rows:
        try:
            # Build dedupe key for within the file
            dedupe_key = (
                (row.symbol or "").strip().upper(),
                row.side,
                round(row.pnl, 2),
                row.entry_time or "",
                row.exit_time or "",
                row.entry_price if row.entry_price is not None else None,
                row.exit_price if row.exit_price is not None else None,
                row.contracts if row.contracts is not None else None,
            )

            if dedupe_key in seen_keys:
                print("CSV import: duplicate row in file skipped:", dedupe_key)
                duplicates += 1
                continue

            seen_keys.add(dedupe_key)

            # 1) derive outcome from pnl
            if row.pnl > 0:
                outcome = "win"
            elif row.pnl < 0:
                outcome = "loss"
            else:
                outcome = "breakeven"

            # 2) timestamps from CSV 
            taken_at = _parse_csv_timestamp(row.entry_time) or datetime.now(
                timezone.utc
            )
            exit_at = _parse_csv_timestamp(row.exit_time)

            # 2b) DB-level dedupe against past imports / manual trades
            symbol_norm = (row.symbol or "").strip()

            if trade_exists_for_user(
                user_id=user_id,
                symbol=symbol_norm,
                side=row.side,
                pnl=row.pnl,
                taken_at=taken_at,
                exit_at=exit_at,
                entry_price=row.entry_price,
                exit_price=row.exit_price,
                contracts=row.contracts,
            ):
                print(
                    "CSV import: DB duplicate skipped:",
                    symbol_norm,
                    row.side,
                    row.pnl,
                    taken_at.isoformat(),
                    exit_at.isoformat() if exit_at else None,
                    row.entry_price,
                    row.exit_price,
                    row.contracts,
                )
                duplicates += 1
                continue

            # 3) try to infer session, but do NOT fail the row if it errors
            session = None
            try:
                session = infer_session_from_entry(taken_at)
            except ValueError as e:
                print("CSV import: session inference failed, continuing:", e)
                session = None

            # 4) actually insert the trade
            insert_trade(
                user_id=user_id,
                note="",  # no note from CSV
                taken_at=taken_at,
                exit_at=exit_at,
                outcome=outcome,
                strategies=None,
                session=session,
                mistakes=None,
                side=row.side,
                entry_price=row.entry_price,
                exit_price=row.exit_price,
                contracts=row.contracts,
                pnl=row.pnl,
                symbol=symbol_norm,
                account_id=account_id,
            )

            inserted += 1
        except Exception as e:
            print("CSV import row failed:", repr(e))
            failed += 1

    return CsvImportResult(insertedCount=inserted, failedCount=failed, skippedCount=duplicates)


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
        strategies=body.strategies,
        session=session,
        mistakes=body.mistakes,
        side=body.side,
        entry_price=body.entryPrice,
        exit_price=body.exitPrice,
        contracts=body.contracts,
        pnl=body.pnl,
        symbol=body.symbol,
    )

    trade = fetch_trade_with_images(user_id=user_id, trade_id=trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="trade_not_found")
    return trade

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
    
    # 4. Load trade to get note + metadata
    trade = fetch_trade_with_images(user_id=user_id, trade_id=trade_id)
    if not trade: 
        raise HTTPException(status_code=404, detail="trade_not_found")
    
    note = trade.get("note") or None

    # Prepare structured metadata for the model
    trade_meta = {
        "taken_at": trade.get("taken_at"),
        "exit_at": trade.get("exit_at"),
        "session": trade.get("session"),
        "side": trade.get("side"),
        "outcome": trade.get("outcome"),
        "strategies": trade.get("strategies") or [],
        "entry_price": trade.get("entry_price"),
        "exit_price": trade.get("exit_price"),
        "contracts": trade.get("contracts"),
        "pnl": trade.get("pnl"),
        "symbol": trade.get("symbol"),
        "mistakes": trade.get("mistakes") or [],
    }

    mime_type = "image/png"

    # 5. Run AI analysis on selected image
    try: 
        analysis = await run_trade_analysis(
            image_bytes=image_bytes,
            mime_type=mime_type,
            user_note=note,
            trade_meta=trade_meta,
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