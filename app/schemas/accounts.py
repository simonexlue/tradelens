from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field

AccountType = Literal["eval", "funded", "live", "sim"]

class AccountBase(BaseModel):
    label: str = Field(..., description="Display name, e.g. 'Topstep 50k")
    provider: Optional[str] = Field(
        default=None,
        description="e.g. 'topstep', 'tradeify', 'apex', 'broker'",
    )
    account_type: Optional[AccountType] = Field(
        default=None,
        description="Evaluation, funded, live etc.",
    )
    size: Optional[float] = Field(
        default=None,
        description="Account size, e.g. 25,000, 50,000",
    )

class AccountCreate(AccountBase):
    """ Body for POST /accounts"""
    #infer from auth

class AccountOut(AccountBase):
    """What we send back to the frontend"""

    id: str
    created_at: datetime

    class Config:
        from_attributes = True