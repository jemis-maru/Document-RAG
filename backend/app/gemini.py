"""
Thin wrapper over the Gemini REST API -- the only paid-if-you-wanted-it part of
the project, used on the free tier for exactly two things:
  1. writing the answer from retrieved chunks
  2. describing chart pages as text (once per page, then cached)

Embeddings and reranking run locally (see models.py), so they never touch the
quota.
"""

import base64
import time

import httpx

from . import config

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

# Bind to an IPv4 local address so connections go over IPv4. httpx tries the
# first DNS answer only, and on networks where IPv6 is advertised but broken
# (DNS returns Google's IPv6 address first) every call would hang until the
# timeout. curl and Node fall back to IPv4 automatically; httpx does not.
_client = httpx.Client(transport=httpx.HTTPTransport(local_address="0.0.0.0"), timeout=120)


class GeminiError(RuntimeError):
    pass


def _api_key() -> str:
    key = config.GEMINI_API_KEY
    if not key or key == "paste_your_key_here":
        raise GeminiError(
            "GEMINI_API_KEY is missing. Put a free key from "
            "https://aistudio.google.com/apikey in backend/.env"
        )
    return key


def _call(model: str, body: dict) -> dict:
    url = f"{API_ROOT}/{model}:generateContent"
    headers = {"x-goog-api-key": _api_key()}
    for attempt in range(3):
        res = _client.post(url, json=body, headers=headers)
        if res.status_code in (429, 500, 503) and attempt < 2:
            # Free tier rate limits are per-minute; a short wait usually clears it.
            time.sleep(5 * (attempt + 1))
            continue
        if res.status_code != 200:
            try:
                detail = res.json()["error"]["message"]
            except Exception:
                detail = res.text[:300]
            raise GeminiError(f"Gemini {res.status_code}: {detail}")
        return res.json()
    raise GeminiError("Gemini kept rate-limiting; try again in a minute")


def generate(
    system: str,
    message: str,
    history: list[dict] | None = None,
    temperature: float = 0.2,
    image_png: bytes | None = None,
) -> str:
    """history: [{"role": "user"|"model", "text": "..."}]"""
    parts: list[dict] = [{"text": message}]
    if image_png:
        parts.append(
            {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(image_png).decode()}}
        )
    contents = [{"role": m["role"], "parts": [{"text": m["text"]}]} for m in history or []]
    contents.append({"role": "user", "parts": parts})

    model = config.CHAT_MODEL
    generation_config: dict = {
        "temperature": temperature,
        # Thinking tokens count against this cap, so leave generous headroom or
        # the visible answer gets cut off mid-sentence.
        "maxOutputTokens": 4096,
    }
    if "gemini-3" in model:
        generation_config["thinkingConfig"] = {"thinkingLevel": "low"}

    data = _call(
        model,
        {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": generation_config,
        },
    )
    candidate = (data.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in candidate.get("content", {}).get("parts", []))
    if not text:
        reason = candidate.get("finishReason") or data.get("promptFeedback", {}).get("blockReason")
        raise GeminiError(f"Gemini returned no text (finishReason: {reason})")
    return text
