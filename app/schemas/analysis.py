import uuid
from typing import List
from pydantic import BaseModel

class AnalyzeTradeBody(BaseModel):
    imageId: uuid.UUID

class AnalysisResponse(BaseModel):
    what_happened: str
    why_result: str
    tips: List[str]