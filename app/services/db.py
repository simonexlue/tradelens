import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any, Set

from supabase import create_client, Client
from ..core.config import settings
from postgrest import APIError
from fastapi import HTTPException

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


def insert_trade(
    user_id: str,
    note: str,
    taken_at: Optional[datetime],
    exit_at: Optional[datetime],
    outcome: Optional[str],
    r_multiple: Optional[float],
    strategy: Optional[str],
    session: Optional[str],
    mistakes: Optional[List[str]],
    side: Optional[str],
    entry_price: Optional[float],
    exit_price: Optional[float],
    contracts: Optional[int],
    pnl: Optional[float],
) -> uuid.UUID:

    payload: Dict[str, Any] = {
        "user_id": user_id,
        "note": note,
        "taken_at": taken_at.isoformat() if taken_at else None,
    }

    if exit_at is not None:
        payload["exit_at"] = exit_at.isoformat()

    if outcome is not None:
        payload["outcome"] = outcome

    if r_multiple is not None:
        payload["r_multiple"] = r_multiple

    if strategy is not None:
        payload["strategy"] = strategy

    if session is not None:
        payload["session"] = session

    if mistakes is not None:
        payload["mistakes"] = mistakes

    if side is not None:
        payload["side"] = side

    if entry_price is not None:
        payload["entry_price"] = entry_price

    if exit_price is not None:
        payload["exit_price"] = exit_price

    if contracts is not None:
        payload["contracts"] = contracts

    if pnl is not None:
        payload["pnl"] = pnl

    res = supabase.table("trades").insert(payload).execute()
    data = res.data or []
    if not data or "id" not in data[0]:
        raise RuntimeError(f"create_failed: {getattr(res, 'error', None)}")

    return uuid.UUID(data[0]["id"])


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
    }
    if width is not None:
        row["width"] = width
    if height is not None:
        row["height"] = height

    try:
        res = supabase.table("images").insert(row).execute()
    except APIError as e:
        print("Supabase insert failed:", e)
        raise HTTPException(
            status_code=400,
            detail=f"DB insert failed: {getattr(e, 'message', str(e))}",
        )

    data = res.data or []
    if not data:
        raise HTTPException(status_code=500, detail="DB insert returned no data")

    rec = data[0]
    # Return a plain JSON-able dict
    return {
        "id": rec["id"],
        "user_id": rec.get("user_id"),
        "trade_id": rec.get("trade_id"),
        "s3_key": rec.get("s3_key"),
        "content_type": rec.get("content_type"),
        "width": rec.get("width"),
        "height": rec.get("height"),
        "created_at": rec.get("created_at"),
    }

def insert_trade_analysis(
    *,
    user_id: str,
    trade_id: uuid.UUID,
    what_happened: str,
    why_result: str,
    tips: List[str],
    model: str,
) -> Dict[str, Any]:
    """
    Insert an AI analysis row for a trade and return the inserted record.
    """
    payload = {
        "user_id": user_id,
        "trade_id": str(trade_id),
        "what_happened": what_happened,
        "why_result": why_result,
        "tips": tips,
        "model": model
    }
    res = supabase.table("trade_analysis").insert(payload).execute()
    data = res.data or []
    if not data:
        raise RuntimeError("analysis_insert_failed")
    
    return data[0]

def fetch_trades_for_user(
    user_id: str,
    limit: int,
    after: Optional[Dict[str, str]] = None,  # {"created_at": ISO, "id": uuid-string}
) -> List[Dict]:
    """
    Returns rows shaped for the frontend list:
    [
      {
        "id": "...",
        "note": "...",
        "created_at": "2025-10-31T19:23:11.123Z",
        "images": [{"s3_key": "...", "width": 1200, "height": 800}],  # zero or one (thumbnail)
        "image_count": 3
      },
      ...
    ]
    Pagination: keyset on (created_at desc, id desc)
    """

    # 1) Base query for trades owned by user (ordered newest first)
    q = (
        supabase.table("trades")
        .select("id, note, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .order("id", desc=True)
    )

    # 2) Keyset pagination: created_at < cursor.created_at OR (created_at = cursor.created_at AND id < cursor.id)
    if after:
        created = after["created_at"]
        tid = after["id"]
        # PostgREST supports boolean OR via .or_("cond1,cond2")
        # Combine the two AND branches as separate groups
        q = q.or_(
            f"and(created_at.lt.{created}),and(created_at.eq.{created},id.lt.{tid})"
        )

    q = q.limit(limit)
    trades_res = q.execute()
    trade_rows = trades_res.data or []

    if not trade_rows:
        return []

    # 3) Fetch images for these trades in one go (no aggregates)
    trade_ids = [str(r["id"]) for r in trade_rows]
    imgs_res = (
        supabase.table("images")
        .select("trade_id, s3_key, width, height, created_at")
        .in_("trade_id", trade_ids)
        .order("created_at", desc=False)  # oldest first
        .execute()
    )
    image_rows = imgs_res.data or []

    # 4) Build maps: first image per trade + per-trade counts
    first_map: Dict[str, Dict] = {}
    count_map: Dict[str, int] = {}

    for img in image_rows:
        tid = str(img["trade_id"])
        count_map[tid] = count_map.get(tid, 0) + 1
        if tid not in first_map:
            first_map[tid] = {
                "s3_key": img["s3_key"],
                "width": img.get("width"),
                "height": img.get("height"),
            }

    # 5) Shape response
    shaped: List[Dict] = []
    for r in trade_rows:
        tid = str(r["id"])
        shaped.append(
            {
                "id": tid,
                "note": r.get("note"),
                "created_at": r.get("created_at"),
                "images": [first_map[tid]] if tid in first_map else [],
                "image_count": int(count_map.get(tid, 0)),
            }
        )

    return shaped


def fetch_trade_with_images(user_id: str, trade_id: uuid.UUID) -> Optional[Dict]:
    trade = (
        supabase.table("trades")
        .select(
            "id, user_id, note, created_at, taken_at, exit_at, outcome, "
            "r_multiple, strategy, session, mistakes, "
            "side, entry_price, exit_price, contracts, pnl"
        )
        .eq("id", str(trade_id))
        .eq("user_id", user_id)
        .single()
        .execute()
        .data
    )
    if not trade:
        return None

    imgs = (
        supabase.table("images")
        .select("id, s3_key, width, height, created_at")
        .eq("trade_id", str(trade_id))
        .order("created_at", desc=False)
        .execute()
        .data
        or []
    )

    analysis_rows = (
        supabase.table("trade_analysis")
        .select("what_happened, why_result, tips, created_at")
        .eq("trade_id", str(trade_id))
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    analysis = analysis_rows[0] if analysis_rows else None

    return {
        "id": str(trade["id"]),
        "note": trade.get("note"),
        "created_at": trade.get("created_at"),
        "taken_at": trade.get("taken_at"),
        "exit_at": trade.get("exit_at"),
        "outcome": trade.get("outcome"),
        "r_multiple": trade.get("r_multiple"),
        "strategy": trade.get("strategy"),
        "session": trade.get("session"),
        "mistakes": trade.get("mistakes"),
        "side": trade.get("side"),
        "entry_price": trade.get("entry_price"),
        "exit_price": trade.get("exit_price"),
        "contracts": trade.get("contracts"),
        "pnl": trade.get("pnl"),
        "images": imgs,
        "analysis": analysis,
    }


def update_trade_note(
    *, user_id: str, trade_id: uuid.UUID, note: str
) -> Optional[Dict[str, Any]]:
    """
    Update the note. We don't rely on return data here.
    """
    res = (
        supabase.table("trades")
        .update({"note": note})
        .eq("id", str(trade_id))
        .eq("user_id", user_id)
        .execute()
    )
    if not res.data:
        return None
    return res.data[0]

def update_trade_fields(
    *,
    user_id: str,
    trade_id: uuid.UUID,
    note: Optional[str] = None,
    taken_at: Optional[datetime] = None,
    exit_at: Optional[datetime] = None,
    outcome: Optional[str] = None,
    r_multiple: Optional[float] = None,
    strategy: Optional[str] = None,
    session: Optional[str] = None,
    mistakes: Optional[List[str]] = None,
    side: Optional[str] = None,
    entry_price: Optional[float] = None,
    exit_price: Optional[float] = None,
    contracts: Optional[int] = None,
    pnl: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """
    Update one or more fields on a trade owned by this user.
    Only non-None parameters are written.
    Note:
      - note=None  -> don't touch note
      - note=""    -> set note to empty string
      - mistakes=None -> don't touch mistakes
      - mistakes=[]   -> set to empty array
    """
    update_payload: Dict[str, Any] = {}

    if note is not None:
        update_payload["note"] = note

    if taken_at is not None:
        update_payload["taken_at"] = taken_at.isoformat()

    if exit_at is not None:
        update_payload["exit_at"] = exit_at.isoformat()

    if outcome is not None:
        update_payload["outcome"] = outcome

    if r_multiple is not None:
        update_payload["r_multiple"] = r_multiple

    if strategy is not None:
        update_payload["strategy"] = strategy

    if session is not None:
        update_payload["session"] = session

    if mistakes is not None:
        update_payload["mistakes"] = mistakes

    if side is not None:
        update_payload["side"] = side

    if entry_price is not None:
        update_payload["entry_price"] = entry_price

    if exit_price is not None:
        update_payload["exit_price"] = exit_price

    if contracts is not None:
        update_payload["contracts"] = contracts

    if pnl is not None:
        update_payload["pnl"] = pnl

    # Nothing to update
    if not update_payload:
        return None

    res = (
        supabase.table("trades")
        .update(update_payload)
        .eq("id", str(trade_id))
        .eq("user_id", user_id)
        .execute()
    )

    data = res.data or []
    if not data:
        # No row updated – either not found or not owned by user
        return None

    return data[0]


def get_image_for_trade(
        *, user_id: str, trade_id: uuid.UUID, image_id: uuid.UUID
) -> Dict[str, Any]:
    """
    Fetch a single image row, ensuring it belongs to the given trade and user.
    Raises LookupError if not found, PermissionError if user mismatch.
    """
    res = (
        supabase.table("images")
        .select("id, user_id, trade_id, s3_key")
        .eq("id", str(image_id))
        .eq("trade_id", str(trade_id))
        .single()
        .execute()
    )

    data = res.data or {}
    if not data:
        raise LookupError("image_not_found")

    if data.get("user_id") != user_id:
        raise PermissionError("image_not_owned")

    return data

def delete_image_record(*, image_id: uuid.UUID) -> None:
    """
    Delete the image row from the images table.
    """
    res = (
        supabase.table("images")
        .delete()
        .eq("id", str(image_id))
        .execute()
    )

def delete_trade_record(*, user_id: str, trade_id: uuid.UUID) -> None:
    """
    Delete a trade row for a given user.
    Raises LookupError if the trade does not exist or is not owned by the user.
    """
    res = (
        supabase.table("trades")
        .delete()
        .eq("id", str(trade_id))
        .eq("user_id", user_id)
        .execute()
    )

    data = res.data or []
    if not data:
        # No row matched (either doesn't exist or not owned by this user)
        raise LookupError("trade_not_found")

def fetch_user_strategies(user_id: str) -> List[str]:
    """
    Return a deduplicated, case-insensitive-sorted list of strategies
    the user has used before.
    """
    res = (
        supabase.table("trades")
        .select("strategy")
        .eq("user_id", user_id)
        .execute()
    )

    rows = res.data or []

    seen_lower: Set[str] = set()
    strategies: List[str] = []

    for r in rows:
        raw = r.get("strategy")
        if not raw:
            continue
        s = raw.strip()
        if not s:
            continue
        key = s.lower()
        if key in seen_lower:
            continue
        seen_lower.add(key)
        strategies.append(s)

    # sort alphabetically, case-insensitive
    strategies.sort(key=lambda x: x.lower())
    return strategies