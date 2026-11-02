"""Optional Google Gemini backend for DI Commerce's primary restaurant assistant.

The provider never receives credentials in frontend code and cannot change
catalogue items, availability, prices, or order state.
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

import httpx

from assistant_engine import SYSTEM_PROMPT, validated_ai_response

DEFAULT_GEMINI_MODEL = 'gemini-3.5-flash-lite'
_MODEL_NAME = re.compile(r"^[a-zA-Z0-9_.-]{3,90}$")


async def gemini_chat(messages: list[dict[str, str]], menu: list[dict[str, Any]],
                      *, key: str, model: str = DEFAULT_GEMINI_MODEL,
                      language: str = "ar", dialect: str = "egyptian") -> dict[str, Any]:
    """Gemini selects an intent/IDs; the server owns wording and priced choices."""
    if not key.strip() or not _MODEL_NAME.fullmatch(model):
        raise ValueError("Gemini is not configured correctly")

    available = [p for p in menu if p["available"]]
    catalogue = [
        {"id": p["id"], "name": p["name"], "category": p["category"],
         "description": p["description"][:160], "tags": p["tags"],
         "price_piasters": p["price_piasters"]}
        for p in available
    ]
    if len(catalogue) > 100:
        # Never pass a partial catalogue as though it were the entire menu.
        raise ValueError("Catalogue exceeds the current Gemini context limit")

    task = {"messages": messages[-12:], "catalogue": catalogue}
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [
            {"text": json.dumps(task, ensure_ascii=False)}
        ]}],
        "generationConfig": {"temperature": 0.35, "maxOutputTokens": 500,
                             "responseMimeType": "application/json"},
    }
    endpoint = ("https://generativelanguage.googleapis.com/v1beta/models/"
                + quote(model, safe="") + ":generateContent")
    async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=4.0)) as client:
        r = await client.post(endpoint, headers={
            "x-goog-api-key": key, "Content-Type": "application/json"
        }, json=payload)
        r.raise_for_status()
        body = r.json()
    candidate = body["candidates"][0]
    if candidate.get('finishReason') != 'STOP':
        raise ValueError('Gemini response was not completed')
    raw = "".join(str(p.get("text", "")) for p in candidate["content"]["parts"]
                  if not p.get('thought'))
    return validated_ai_response(json.loads(raw), menu, provider='gemini',
                                 language=language, dialect=dialect)
