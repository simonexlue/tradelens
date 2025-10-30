import uuid
from fastapi import APIRouter, Depends, HTTPException
from ...schemas.uploads import PresignBody, PresignResponse
from ...schemas.common import MIME_TO_EXT
from ...services.aws import gen_key, presign_put
from ...services.db import check_trade_belongs_to_user
from ..deps import get_current_user_id

router = APIRouter(prefix="/uploads", tags=["uploads"])

@router.post("/presign", response_model=PresignResponse)
def presign_upload(body: PresignBody, user_id: str = Depends(get_current_user_id)):
    # ext ↔ mime validation
    expected = MIME_TO_EXT[body.contentType]
    ext = "jpg" if body.fileExt == "jpeg" else body.fileExt
    if ext != expected:
        raise HTTPException(status_code=400, detail="bad_extension_for_mime")

    trade_id = body.tradeId or uuid.uuid4()
    if body.tradeId:
        try:
            check_trade_belongs_to_user(trade_id, user_id)
        except LookupError:
            raise HTTPException(status_code=404, detail="trade_not_found")
        except PermissionError:
            raise HTTPException(status_code=403, detail="trade_not_owned")

    key = gen_key(user_id, trade_id, ext)
    try:
        url = presign_put(key, body.contentType)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return PresignResponse(uploadUrl=url, key=key, contentType=body.contentType)
