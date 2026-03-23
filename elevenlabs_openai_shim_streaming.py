"""
ElevenLabs OpenAI Shim (Streaming) — OpenAI-compatible /v1/audio/speech endpoint.

This service accepts an OpenAI-compatible JSON request body for
`/v1/audio/speech`, but it does not implement full OpenAI speech behavior.
It calls the ElevenLabs API and streams the audio response back to the client as chunks arrive,
reducing time-to-first-byte significantly for longer texts.

Compatibility
-------------
Only the `input` field is used for normal speech synthesis.

Other request fields are ignored, except for the special `voice` value
`the-voice-in-your-head`, which triggers a built-in easter egg response.

This makes it possible for existing clients to switch the endpoint URL to
this service while continuing to send the same general request shape.

Setup
-----
    python3 -m venv .venv
    source .venv/bin/activate
    pip install fastapi uvicorn httpx python-dotenv

Configuration (.env)
--------------------
    XI_API_KEY=sk_...                          # Required – ElevenLabs API key
    ELEVENLABS_VOICE_ID=abc123                 # Required – server-side voice ID
    ELEVENLABS_MODEL_ID=eleven_multilingual_v2 # Optional – server-side model
    DEFAULT_FORMAT=pcm_24000                   # Optional – ElevenLabs output format
    DEFAULT_CONTENT_TYPE=audio/wav             # Optional – response content type

Run
---
    uvicorn elevenlabs_openai_shim_streaming:app --host 127.0.0.1 --port 8881

Example request
---------------
    curl -X POST http://127.0.0.1:8881/v1/audio/speech \\
         -H "Content-Type: application/json" \\
         -d '{"input": "Hello world"}' \\
         --output speech.audio

Behavior
--------
- `input` is required and is the only field used for synthesis.
- Other OpenAI-style fields such as `model`, `voice`, `instructions`,
  `response_format`, `speed`, and `stream_format` are accepted for
  compatibility but ignored.
- Speech generation is controlled by server-side configuration.

Audio format note
-----------------
The response format is controlled by the server configuration, not by the
incoming request body.

When `DEFAULT_FORMAT` is set to `pcm_24000`, ElevenLabs returns raw
headerless PCM audio (24 kHz, 16-bit, mono). This is NOT a valid WAV file,
even if the response content type is configured as `audio/wav`, because no
RIFF/WAV header is included.

Clients must handle the raw PCM stream directly or wrap it in a WAV container
themselves.
"""

import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

EASTER_EGG_VOICE = "the-voice-in-your-head"
STATIC_DIR = Path(__file__).resolve().parent / "static"

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

XI_API_KEY = os.getenv("XI_API_KEY", "")
DEFAULT_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")
DEFAULT_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
DEFAULT_FORMAT = os.getenv("DEFAULT_FORMAT", "pcm_24000")
DEFAULT_CONTENT_TYPE = os.getenv("DEFAULT_CONTENT_TYPE", "audio/wav")

# IP-based character limit. Empty ALLOWED_IPS disables the feature entirely.
_allowed_raw = os.getenv("ALLOWED_IPS", "")
ALLOWED_IPS: set[str] = {ip.strip() for ip in _allowed_raw.split(",") if ip.strip()} if _allowed_raw else set()
CHAR_LIMIT = int(os.getenv("CHAR_LIMIT", "2000"))
char_usage: dict[str, int] = {}

if not XI_API_KEY:
    logger.warning("XI_API_KEY is not set — requests will fail until configured")
if not DEFAULT_VOICE_ID:
    logger.warning("ELEVENLABS_VOICE_ID is not set — requests will fail until configured")
if ALLOWED_IPS:
    logger.info("Character limit active: %d chars for non-whitelisted IPs", CHAR_LIMIT)

http_client: Optional[httpx.AsyncClient] = None


async def get_payload(request: Request) -> dict[str, Any]:
    try:
        payload: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")

    logger.info("Incoming request body: %s", payload)
    return payload


def get_input_text(payload: dict[str, Any]) -> str:
    if "input" not in payload:
        raise HTTPException(status_code=400, detail="Missing required field: input")

    input_value = payload["input"]

    if not isinstance(input_value, str):
        raise HTTPException(status_code=400, detail="Field 'input' must be a string")

    input_value = input_value.strip()

    if not input_value:
        raise HTTPException(status_code=400, detail="Field 'input' must not be empty")

    if len(input_value) > 4096:
        raise HTTPException(status_code=400, detail="Field 'input' exceeds maximum length of 4096 characters")

    return input_value

@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=120.0))
    logger.info("ElevenLabs OpenAI shim (streaming) started")
    yield
    await http_client.aclose()
    logger.info("ElevenLabs OpenAI shim (streaming) stopped")


app = FastAPI(title="ElevenLabs OpenAI Shim (Streaming)", lifespan=lifespan)

def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "api_key_set": bool(XI_API_KEY),
        "default_voice_set": bool(DEFAULT_VOICE_ID)
    }


@app.post("/v1/audio/speech")
async def audio_speech(request: Request):
    if not DEFAULT_VOICE_ID:
        raise HTTPException(status_code=500, detail="Missing ELEVENLABS_VOICE_ID env var")

    # Use API key from Authorization header if provided, otherwise fall back to server default.
    auth_header = request.headers.get("authorization", "")
    api_key = auth_header.removeprefix("Bearer ").strip() if auth_header.lower().startswith("bearer ") else ""
    if not api_key:
        api_key = XI_API_KEY
    if not api_key:
        raise HTTPException(status_code=500, detail="Missing API key: set XI_API_KEY env var or pass Authorization header")

    payload = await get_payload(request)

    # Easter egg: return a canned "The Force" audio clip.
    if payload.get("voice") == EASTER_EGG_VOICE:
        logger.info("Easter egg activated: the-voice-in-your-head")
        static_file = STATIC_DIR / "the_force.pcm"
        if not static_file.exists():
            raise HTTPException(status_code=500, detail="Missing easter egg audio file")
        return Response(content=static_file.read_bytes(), media_type=DEFAULT_CONTENT_TYPE)

    input_text = get_input_text(payload)

    # Use voice from request if it looks like an ElevenLabs voice ID (20-char alphanumeric),
    # otherwise fall back to server default. OpenAI-style names like "alloy" are ignored.
    req_voice = payload.get("voice")
    voice_id = req_voice if isinstance(req_voice, str) and re.fullmatch(r"[a-zA-Z0-9]{20}", req_voice) else DEFAULT_VOICE_ID

    # Use model from request if it looks like an ElevenLabs model ID,
    # otherwise fall back to server default. OpenAI-style names like "tts-1" are ignored.
    req_model = payload.get("model")
    model_id = req_model if isinstance(req_model, str) and req_model.startswith("eleven_") else DEFAULT_MODEL_ID

    # IP-based character limit (skipped for easter egg above).
    if ALLOWED_IPS:
        client_ip = get_client_ip(request)
        if client_ip not in ALLOWED_IPS:
            char_usage[client_ip] = char_usage.get(client_ip, 0) + len(input_text)
            if char_usage[client_ip] > CHAR_LIMIT:
                logger.warning("Char limit exceeded for %s (%d/%d)", client_ip, char_usage[client_ip], CHAR_LIMIT)
                raise HTTPException(status_code=429, detail="Character limit exceeded")

    logger.info(
        "TTS request: voice=%s model=%s format=%s chars=%d",
        voice_id,
        model_id,
        DEFAULT_FORMAT,
        len(input_text),
    )

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream?output_format={DEFAULT_FORMAT}"

    if http_client is None:
        raise HTTPException(status_code=500, detail="HTTP client is not initialized")
    upstream = await http_client.send(
        http_client.build_request(
            "POST",
            url,
            headers={
                "xi-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": DEFAULT_CONTENT_TYPE,
            },
            json={
                "text": input_text,
                "model_id": model_id,
            },
        ),
        stream=True,
    )

    if upstream.status_code != 200:
        # Must read the body to get the error, then close.
        body = await upstream.aread()
        await upstream.aclose()
        try:
            import json
            detail = json.loads(body)
        except Exception:
            detail = body.decode(errors="replace")[:500]
        logger.error("ElevenLabs error %d: %s", upstream.status_code, detail)
        raise HTTPException(status_code=upstream.status_code, detail=detail)

    async def stream_chunks():
        total_bytes = 0
        try:
            async for chunk in upstream.aiter_bytes(chunk_size=4096):
                total_bytes += len(chunk)
                yield chunk
        finally:
            await upstream.aclose()
            logger.info("TTS stream complete: %d bytes", total_bytes)

    return StreamingResponse(
        stream_chunks(),
        media_type=DEFAULT_CONTENT_TYPE,
        headers={"Transfer-Encoding": "chunked"},
    )
