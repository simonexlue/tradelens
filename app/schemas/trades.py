import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class CreateTradeBody(BaseModel):
    note: Optional[str] = Field(default="", min_length=0, max_length=1000)
    takenAt: Optional[datetime] = None

class CreateTradeResponse(BaseModel):
    tradeId: uuid.UUID
