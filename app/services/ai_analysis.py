import os
import json
from typing import Any, Dict, List, TypedDict

from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

class AnalysisResult(TypedDict):
    what_happened: str
    why_result: str
    tips: List[str]

SYSTEM_PROMPT = """
You are a trading coach analyzing futures/indices trades from chart screenshots.

Your job:
1) Explain in simple language what happened in the trade.
2) Explain **why** the trade worked or failed, based on structure, trend, liquidity, and timing.
3) Give 2–3 actionable tips the trader can apply next time.

Rules:
- Be specific to the chart (EMAs, structure, key levels).
- Do not give financial advice or signal services.
- Keep the tone coaching-focused, not judgmental.
"""

def build_user_prompt(user_note: str | None) -> str:
    note_text = user_note or "No note provided."
    return f"""
User's trade note:
{note_text}

Using the chart image + this note, analyze the trade.
Return ONLY JSON in this shape:

{{
  "what_happened": "one concise but detailed paragraph",
  "why_result": "one concise but detailed paragraph explaining why it worked or failed",
  "tips": [
    "short actionable tip 1",
    "short actionable tip 2",
    "short actionable tip 3"
  ]
}}
"""

async def run_trade_analysis(
    image_bytes: bytes,
    mime_type: str,
    user_note: str | None,
) -> AnalysisResult:
    """
    Takes raw image bytes + MIME type + note → structured analysis JSON.
    """

    response = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {
                "role": "system",
                "content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_image",
                        "image": {
                            "data": image_bytes,
                            "mime_type": mime_type,
                        },
                    },
                    {
                        "type": "input_text",
                        "text": build_user_prompt(user_note),
                    },
                ],
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "trade_analysis",
                "schema": {
                    "type": "object",
                    "properties": {
                        "what_happened": {"type": "string"},
                        "why_result": {"type": "string"},
                        "tips": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 2,
                            "maxItems": 4,
                        },
                    },
                    "required": ["what_happened", "why_result", "tips"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        },
    )

    # end goal: turn response into a dict[what_happened, why_result, tips[]].
    content = response.output[0].content[0].parsed
    return AnalysisResult(
        what_happened=content["what_happened"],
        why_result=content["why_result"],
        tips=content["tips"],
    )