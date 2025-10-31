import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict
from .common import AllowedContentType

class CreateImageBody(BaseModel):
    key: str
    contentType: str
    width: Optional[int] = None 
    height: Optional[int] = None

class CreateImageResponse(BaseModel):
    imageId: uuid.UUID
    s3Key: str
    createdAt: datetime
