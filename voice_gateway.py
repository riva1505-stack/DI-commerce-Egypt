"""Optional, server-side speech-to-text and text-to-speech integration.

Never expose API keys to a browser. Audio is relayed in memory; this module
neither saves nor logs voice recordings. Speech provider still processes audio.
"""
from __future__ import annotations

import httpx

API_ROOT = "https://api.openai.com/v1/audio"


async def transcribe_audio(raw: bytes, filename: str, mime: str, *, api_key: str,
                           model: str = "gpt-4o-mini-transcribe", language: str = "ar") -> str:
    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
        result = await client.post(
            f"{API_ROOT}/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            data={"model": model, "language": language if language in ("ar", "en", "fr") else "ar"},
            files={"file": (filename, raw, mime)},
        )
        result.raise_for_status()
        value = result.json().get("text", "")
        return str(value).strip()[:500]


async def synthesize_speech(text: str, *, api_key: str,
                            model: str = "gpt-4o-mini-tts",
                            voice: str = "coral", language: str = "ar", dialect: str = "egyptian") -> bytes:
    voice_instructions = {
        "en": "Speak in polished, friendly, professional English with a natural conversational rhythm. Pronounce menu items accurately. Read only the supplied text.",
        "fr": "Parlez en français naturel, professionnel et chaleureux, avec une prononciation claire. Lisez uniquement le texte fourni.",
        "ar-egyptian": "اتكلم بعامية مصرية طبيعية ودودة، بدون تكلف وبسرعة مريحة. انطق أسماء الأكلات بشكل واضح. اقرأ النص المكتوب فقط.",
        "ar-lebanese": "احكي باللهجة اللبنانية الطبيعية، بنبرة لطيفة وعفوية، ومن دون مبالغة. انطق أسماء الأكلات بوضوح. اقرأ النص المكتوب فقط.",
        "ar-standard": "تحدث بالعربية الفصحى الواضحة بصوت طبيعي مهذب. اقرأ النص المكتوب فقط.",
    }
    speech_style = language if language in ("en", "fr") else "ar-" + (dialect if dialect in ("egyptian", "lebanese", "standard") else "egyptian")
    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
        result = await client.post(
            f"{API_ROOT}/speech",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "voice": voice,
                "input": text,
                "response_format": "mp3",
                "instructions": voice_instructions[speech_style],
            },
        )
        result.raise_for_status()
        return result.content
