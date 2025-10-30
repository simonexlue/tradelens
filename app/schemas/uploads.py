import uuid
from pydantic import BaseModel, Field
from typing import Optional
from .common import AllowedContentType, AllowedExt

class PresignBody(BaseModel):
    contentType: AllowedContentType
    fileExt: AllowedExt
    size: int = Field(gt=0, le=10_000_000)
    tradeId: Optional[uuid.UUID] = None

class PresignResponse(BaseModel):
    uploadUrl: str
    key: str
    expiresIn: int = 900
    contentType: AllowedContentType
    contentLengthRange: dict = {"min": 1, "max": 10_000_000}
