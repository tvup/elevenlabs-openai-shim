# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A thin Python shim that translates OpenAI-compatible `/v1/audio/speech` TTS requests into ElevenLabs API calls. Any client expecting the OpenAI speech endpoint can use ElevenLabs voices transparently.

## Running the Service

```bash
# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn httpx python-dotenv

# Run streaming variant (recommended, used by Docker)
uvicorn elevenlabs_openai_shim_streaming:app --host 127.0.0.1 --port 8881

# Run non-streaming variant
uvicorn elevenlabs_openai_shim:app --host 127.0.0.1 --port 8881

# Docker
docker compose up -d
```

## Architecture

Two standalone FastAPI apps (no shared code between them):

- **`elevenlabs_openai_shim.py`** — Buffers full ElevenLabs response before returning to client.
- **`elevenlabs_openai_shim_streaming.py`** — Streams 4KB chunks via `StreamingResponse`, calls ElevenLabs `/stream` endpoint variant. Lower TTFB, lower memory. This is the default in Docker.

Both expose:
- `POST /v1/audio/speech` — Accepts OpenAI-style JSON, proxies to ElevenLabs TTS
- `GET /health` — Returns config status

## Key Behavior

- **PINNED_FORMAT**: Hardcoded to `"wav"` in both files. Overrides any client-requested format. Set to `None` to respect client requests.
- **Format mapping**: `"mp3"`/`"mpeg"` → ElevenLabs `mp3_44100_128`; anything else → `pcm_24000` (raw headerless PCM, not a standard WAV file).
- **Voice/model resolution**: Request fields override env vars (`ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL_ID`). Model defaults to `eleven_multilingual_v2`.
- **Easter egg**: Voice `the-voice-in-your-head` returns a pre-generated "The Force" audio clip from `static/` without calling ElevenLabs.

## Environment Variables (`.env`)

| Variable | Required | Description |
|---|---|---|
| `XI_API_KEY` | Yes | ElevenLabs API key |
| `ELEVENLABS_VOICE_ID` | Yes | Default voice ID (used when request omits `voice`) |
| `ELEVENLABS_MODEL_ID` | No | Default model (defaults to `eleven_multilingual_v2`) |

## Dependencies

Python 3.12, FastAPI, Uvicorn, httpx, python-dotenv. No requirements.txt — deps are installed directly in Dockerfile.
