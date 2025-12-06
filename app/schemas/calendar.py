from typing import List
from pydantic import BaseModel, Field

class CalendarDay(BaseModel):    
    """
    Summary of trades for a single calendar day.
    """
    date: str = Field(
        ...,
        description="Date in YYYY-MM-DD (UTC) derived from taken_at",
        examples=["2025-12-01"],
    )
    pnl: float = Field(
        ...,
        description="Net profit/loss for that day",
        examples=[305.0, -656.8],
    )
    trade_count: int = Field(
        ...,
        description="Number of trades taken that day",
        examples=[2, 11],
    )

class CalendarResponse(BaseModel):
    """
    Calendar view response: list of daily summaries for a given month.
    """
    days: List[CalendarDay]