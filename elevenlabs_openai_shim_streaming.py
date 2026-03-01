"""
ElevenLabs OpenAI Shim (Streaming) — OpenAI-compatible /v1/audio/speech endpoint.

A thin compatibility layer that translates OpenAI-style TTS requests into
ElevenLabs API calls and streams the audio response back to the client as
chunks arrive, reducing time-to-first-byte significantly for longer texts.

Setup
-----
    python3 -m venv .venv
    source .venv/bin/activate
    pip install fastapi uvicorn httpx python-dotenv

Configuration (.env)
--------------------
    XI_API_KEY=sk_...                          # Required – ElevenLabs API key
    ELEVENLABS_VOICE_ID=abc123                 # Required – default voice ID
    ELEVENLABS_MODEL_ID=eleven_multilingual_v2 # Optional – model override

Run
---
    uvicorn elevenlabs_openai_shim_streaming:app --host 127.0.0.1 --port 8881

Example request
---------------
    curl -X POST http://127.0.0.1:8881/v1/audio/speech \\
         -H "Content-Type: application/json" \\
         -d '{"input": "Hello world", "format": "mp3"}' \\
         --output speech.mp3

Audio format note
-----------------
    When format is "wav", ElevenLabs returns raw headerless PCM via their
    pcm_24000 output format (24 kHz, 16-bit, mono). This is NOT a valid WAV
    file — it contains no RIFF/WAV header. Clients must handle the raw PCM
    stream directly or wrap it in a WAV container themselves.

    MP3 output (mp3_44100_128) is a standard self-contained file.
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

XI_API_KEY = os.getenv("XI_API_KEY", "")
DEFAULT_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")
DEFAULT_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")

# Set to a format string (e.g. "wav", "mp3") to override client-requested format.
# Set to None to let the client choose via request parameters.
PINNED_FORMAT: Optional[str] = "wav"

if not XI_API_KEY:
    logger.warning("XI_API_KEY is not set — requests will fail until configured")
if not DEFAULT_VOICE_ID:
    logger.warning("ELEVENLABS_VOICE_ID is not set — requests without explicit voice will fail")

http_client: Optional[httpx.AsyncClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=120.0))
    logger.info("ElevenLabs OpenAI shim (streaming) started")
    logger.info("Pinned format: %s", PINNED_FORMAT or "none (client chooses)")
    yield
    await http_client.aclose()
    logger.info("ElevenLabs OpenAI shim (streaming) stopped")


app = FastAPI(title="ElevenLabs OpenAI Shim (Streaming)", lifespan=lifespan)


class SpeechRequest(BaseModel):
    input: str
    model: Optional[str] = None
    voice: Optional[str] = None
    response_format: Optional[str] = None
    format: Optional[str] = "wav"


def resolve_format(fmt: str) -> tuple[str, str]:
    """Map a requested format to an ElevenLabs output_format and HTTP content type."""
    if fmt in ("mp3", "mpeg"):
        return "mp3_44100_128", "audio/mpeg"
    # "wav" / "wave" / anything else → raw PCM (see docstring at top of file).
    return "pcm_24000", "audio/wav"


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "api_key_set": bool(XI_API_KEY),
        "default_voice_set": bool(DEFAULT_VOICE_ID),
        "pinned_format": PINNED_FORMAT,
    }


@app.post("/v1/audio/speech")
async def audio_speech(req: SpeechRequest):
    if not XI_API_KEY:
        raise HTTPException(status_code=500, detail="Missing XI_API_KEY env var")

    voice_id = req.voice or DEFAULT_VOICE_ID
    if not voice_id:
        raise HTTPException(status_code=500, detail="Missing ELEVENLABS_VOICE_ID env var")

    # Pinned format takes precedence; otherwise honour the client's choice.
    if PINNED_FORMAT:
        fmt = PINNED_FORMAT
    else:
        fmt = (req.response_format or req.format or "wav").lower()

    output_format, content_type = resolve_format(fmt)

    model_id = req.model or DEFAULT_MODEL_ID

    logger.info(
        "TTS request: voice=%s model=%s format=%s chars=%d",
        voice_id,
        model_id,
        output_format,
        len(req.input),
    )

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream?output_format={output_format}"

    upstream = await http_client.send(
        http_client.build_request(
            "POST",
            url,
            headers={
                "xi-api-key": XI_API_KEY,
                "Content-Type": "application/json",
                "Accept": content_type,
            },
            json={
                "text": req.input,
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
        media_type=content_type,
        headers={"Transfer-Encoding": "chunked"},
    )
