import os
import json
import base64 
from typing import Any, Dict, List, TypedDict
from ..core.config import settings

from openai import OpenAI


api_key = settings.openai_api_key
if not api_key:
    raise RuntimeError("OPENAI_API_KEY not configured in settings/.env")

client = OpenAI(api_key=api_key)

class AnalysisResult(TypedDict):
    what_happened: str
    why_result: str
    tips: List[str]

SYSTEM_PROMPT = """
You are a trading coach analyzing futures/indices trades from chart screenshots.

Your job:
1) Explain in simple language what happened in the trade. IMPORTANT: Make sure to state the position (buy/sell), points won/lost calculated from the entry and exit price or from the notes.
2) Explain **why** the trade worked or failed, based on structure, trend, liquidity, timing, and the provided trade metadata.
3) Give 2–3 relatable and actionable tips the trader can apply next time, related to the current trade they just took.

Rules:
- Be specific to the chart (EMAs, structure, key levels) AND consistent with the metadata.
- If metadata fields are null or missing, do not invent values. Just ignore those fields. And remind trader at the end to fill out those values for better insights.
- If the outcome is a loss or negative PnL, lean into coaching: focus on what can be improved, not shaming.
- If the outcome is a loss or negative PnL, suggest what they should look for next time before taking the trade.
- Do not give financial advice or signal services (no “you should buy/sell now”).
- Always assume take profit and stop loss is set by trader
- Keep the tone coaching-focused, not judgmental.
"""

def build_user_prompt(user_note: str | None, trade_meta: dict | None) -> str:
    note_text = user_note or "No note provided."

    if trade_meta:
        meta_json = json.dumps(trade_meta, indent=2, default=str)
        meta_block = f"Trade metadata (JSON):\n{meta_json}"
    else:
        meta_block = "Trade metadata: None (no extra fields supplied)"
    return f"""

{meta_block}

User's trade note:
{note_text}

Using the chart image + this note + the metadata, analyze the trade.
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
    trade_meta: dict | None,
) -> AnalysisResult:
    """
    Takes raw image bytes + MIME type + note → structured analysis JSON.
    """

    # Encode image as base64 string for the API (bytes are not JSON-serializable)
    b64_image = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{b64_image}"

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
                        # Responses API expects image_url, not image
                        "image_url": data_url
                    },
                    {
                        "type": "input_text",
                        "text": build_user_prompt(user_note, trade_meta),
                    },
                ],
            },
        ],
        # no response_format here because openai==2.8.1 Responses.create
        # does not support that kwarg yet. We instead parse JSON from the text output.
    )

    # end goal: turn response into a dict[what_happened, why_result, tips[]].
    # We tell the model to return ONLY JSON, then parse it here.
    try:
        # Prefer convenience attribute if available
        text = getattr(response, "output_text", None)

        if not text:
            # Fallback: dig into first output block
            block = response.output[0]          # type: ignore[index]
            part = block.content[0]             # type: ignore[index]

            text = getattr(part, "text", None)
            if text is None and isinstance(part, dict):
                text = part.get("text")

        if not text:
            raise RuntimeError("No text field found in OpenAI response")

        raw = text.strip()

        # If the model wrapped JSON in ```json ... ``` code fences, strip them
        if raw.startswith("```"):
            # Drop opening ```... line
            lines = raw.splitlines()
            if len(lines) >= 2:
                # remove first line (``` or ```json) and any trailing ``` line
                if lines[0].lstrip().startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip().startswith("```"):
                    lines = lines[:-1]
                raw = "\n".join(lines).strip()

        content = json.loads(raw)
    except Exception as e:
        print("Unexpected OpenAI response structure or JSON:", response)
        raise RuntimeError(f"failed_to_parse_openai_response: {e!r}")

    return AnalysisResult(
        what_happened=content["what_happened"],
        why_result=content["why_result"],
        tips=content["tips"],
    )
