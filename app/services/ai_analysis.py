import os
import json
import base64  # 👈 already added earlier
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
                        # NOTE: Responses API expects image_url, not image
                        "image_url": data_url
                    },
                    {
                        "type": "input_text",
                        "text": build_user_prompt(user_note),
                    },
                ],
            },
        ],
        # NOTE: no response_format here because openai==2.8.1 Responses.create
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
