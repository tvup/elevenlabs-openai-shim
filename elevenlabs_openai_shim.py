"""
ElevenLabs OpenAI Shim — OpenAI-compatible /v1/audio/speech endpoint.

A thin compatibility layer that translates OpenAI-style TTS requests into
ElevenLabs API calls, so any client expecting the OpenAI speech endpoint
can use ElevenLabs voices instead.

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
    uvicorn elevenlabs_openai_shim:app --host 127.0.0.1 --port 8881

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
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel

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

# Set to a format string (e.g. "wav", "mp3") to override client-requested format.
# Set to None to let the client choose via request parameters.
PINNED_FORMAT: Optional[str] = "wav"

# IP-based character limit. Empty ALLOWED_IPS disables the feature entirely.
_allowed_raw = os.getenv("ALLOWED_IPS", "")
ALLOWED_IPS: set[str] = {ip.strip() for ip in _allowed_raw.split(",") if ip.strip()} if _allowed_raw else set()
CHAR_LIMIT = int(os.getenv("CHAR_LIMIT", "2000"))
char_usage: dict[str, int] = {}

if not XI_API_KEY:
    logger.warning("XI_API_KEY is not set — requests will fail until configured")
if not DEFAULT_VOICE_ID:
    logger.warning("ELEVENLABS_VOICE_ID is not set — requests without explicit voice will fail")
if ALLOWED_IPS:
    logger.info("Character limit active: %d chars for non-whitelisted IPs", CHAR_LIMIT)

http_client: Optional[httpx.AsyncClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(timeout=60)
    logger.info("ElevenLabs OpenAI shim started")
    logger.info("Pinned format: %s", PINNED_FORMAT or "none (client chooses)")
    yield
    await http_client.aclose()
    logger.info("ElevenLabs OpenAI shim stopped")


app = FastAPI(title="ElevenLabs OpenAI Shim", lifespan=lifespan)


class SpeechRequest(BaseModel):
    input: str
    model: Optional[str] = None
    voice: Optional[str] = None
    response_format: Optional[str] = None
    format: Optional[str] = "wav"


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


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
async def audio_speech(req: SpeechRequest, request: Request):
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

    # Easter egg: return a canned "The Force" audio clip.
    if voice_id == EASTER_EGG_VOICE:
        logger.info("Easter egg activated: the-voice-in-your-head")
        static_file = STATIC_DIR / ("the_force.mp3" if fmt in ("mp3", "mpeg") else "the_force.pcm")
        return Response(content=static_file.read_bytes(), media_type=content_type)

    # IP-based character limit (skipped for easter egg above).
    if ALLOWED_IPS:
        client_ip = get_client_ip(request)
        if client_ip not in ALLOWED_IPS:
            char_usage[client_ip] = char_usage.get(client_ip, 0) + len(req.input)
            if char_usage[client_ip] > CHAR_LIMIT:
                logger.warning("Char limit exceeded for %s (%d/%d)", client_ip, char_usage[client_ip], CHAR_LIMIT)
                raise HTTPException(status_code=422, detail="Character limit exceeded")

    logger.info(
        "TTS request: voice=%s model=%s format=%s chars=%d",
        voice_id,
        req.model or DEFAULT_MODEL_ID,
        output_format,
        len(req.input),
    )

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format={output_format}"

    r = await http_client.post(
        url,
        headers={
            "xi-api-key": XI_API_KEY,
            "Content-Type": "application/json",
            "Accept": content_type,
        },
        json={
            "text": req.input,
            "model_id": req.model or DEFAULT_MODEL_ID,
        },
    )

    if r.status_code != 200:
        try:
            detail = r.json()
        except Exception:
            detail = r.text[:500]
        logger.error("ElevenLabs error %d: %s", r.status_code, detail)
        raise HTTPException(status_code=r.status_code, detail=detail)

    logger.info("TTS response: %d bytes", len(r.content))
    return Response(content=r.content, media_type=content_type)
