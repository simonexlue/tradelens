import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

class CreateTradeBody(BaseModel):
    note: Optional[str] = Field(default="", min_length=0, max_length=1000)
    takenAt: Optional[datetime] = None
    exitAt: Optional[datetime] = None 
    outcome: Optional[str] = Field(
        default = None, 
        description="Outcome of the trade: win, loss, breakeven, early_exit",   
    )
    rMultiple: Optional[float] = Field(
        default=None,
        description="R multiple for the trade (risk-reward in R)",
    )
    strategy: Optional[str] = Field(
        default=None,
        description="User-defined strategy label"
    )
    mistakes: Optional[List[str]] = Field(
        default=None,
        description="List of mistakes for this trade (AI suggested + user edited)"
    )

class CreateTradeResponse(BaseModel):
    tradeId: uuid.UUID

class UpdateTradeBody(BaseModel):
    note: Optional[str] = Field(
        default=None,
        description="Updated note for the trade",
    )
    takenAt: Optional[datetime] = None
    exitAt: Optional[datetime] = None
    outcome: Optional[str] = None
    rMultiple: Optional[float] = None
    strategy: Optional[str] = None
    mistakes: Optional[List[str]] = None