"""Optional, server-side speech-to-text and text-to-speech integration.

Never expose API keys to a browser. Audio is relayed in memory; this module
neither saves nor logs voice recordings. Speech provider still processes audio.
"""
from __future__ import annotations

import httpx

API_ROOT = "https://api.openai.com/v1/audio"


async def transcribe_audio(raw: bytes, filename: str, mime: str, *, api_key: str,
                           model: str = "gpt-4o-mini-transcribe") -> str:
    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
        result = await client.post(
            f"{API_ROOT}/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            data={"model": model, "language": "ar"},
            files={"file": (filename, raw, mime)},
        )
        result.raise_for_status()
        value = result.json().get("text", "")
        return str(value).strip()[:500]


async def synthesize_speech(text: str, *, api_key: str,
                            model: str = "gpt-4o-mini-tts",
                            voice: str = "coral") -> bytes:
    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
        result = await client.post(
            f"{API_ROOT}/speech",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "voice": voice,
                "input": text,
                "response_format": "mp3",
                "instructions": "اتكلم بالعربي بلهجة مصرية ودودة، بنبرة طبيعية وسرعة متوسطة، زي موظف استقبال مطعم. لا تضف أي كلام غير النص المكتوب.",
            },
        )
        result.raise_for_status()
        return result.content
