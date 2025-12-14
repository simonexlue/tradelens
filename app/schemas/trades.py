from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
import uuid

class CreateTradeBody(BaseModel):
    note: Optional[str] = Field(default="", min_length=0, max_length=3000)
    takenAt: Optional[datetime] = None
    exitAt: Optional[datetime] = None 
    outcome: Optional[str] = Field(
        default=None,
        description="Outcome of the trade: win, loss, breakeven, early_exit",
    )
    strategies: Optional[List[str]] = Field(
        default=None,
        description="List of strategy labels (tags) for this trade",
    )
    mistakes: Optional[List[str]] = Field(
        default=None,
        description="List of mistakes for this trade (AI suggested + user edited)",
    )
    side: Optional[str] = Field(
        default=None,
        description="buy or sell",
    )
    entryPrice: Optional[float] = Field(
        default=None,
        description="Entry price of the trade",
    )
    exitPrice: Optional[float] = Field(
        default=None,
        description="Exit price of the trade",
    )
    contracts: Optional[int] = Field(
        default=None,
        description="Number of contracts",
    )
    pnl: Optional[float] = Field(
        default=None,
        description="Profit and loss in currency",
    )
    symbol: Optional[str] = None
    accountId: Optional[uuid.UUID] = Field(
        default=None,
        description="Account this trade belongs to (accounts.id)",
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
    strategies: Optional[List[str]] = None
    mistakes: Optional[List[str]] = None
    side: Optional[str] = None
    entryPrice: Optional[float] = None
    exitPrice: Optional[float] = None
    contracts: Optional[int] = None
    pnl: Optional[float] = None
    symbol: Optional[str] = None

class CsvImportRow(BaseModel):
    symbol: str
    side: str  # "buy" | "sell"
    pnl: float
    entry_time: Optional[str] = None
    exit_time: Optional[str] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    contracts: Optional[int] = None
    duration: Optional[int] = None

class CsvImportRequest(BaseModel):
    rows: List[CsvImportRow]
    accountId: Optional[uuid.UUID] = None

class CsvImportResult(BaseModel):
    insertedCount: int
    failedCount: int
    skippedCount: int

class TradeStatsResponse(BaseModel):
    todayPnl: float
    weekPnl: float
    winRateLast30: float
    avgPnlLast30: float #change to R multiple later