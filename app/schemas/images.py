import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from .common import AllowedContentType

class CreateImageBody(BaseModel):
    key: str
    contentType: AllowedContentType
    width: Optional[int] = Field(default=None, ge=1)
    height: Optional[int] = Field(default=None, ge=1)

class CreateImageResponse(BaseModel):
    imageId: uuid.UUID
    s3Key: str
    createdAt: datetime
