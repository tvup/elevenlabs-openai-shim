# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python shim that accepts OpenAI-compatible `/v1/audio/speech` requests and generates speech using ElevenLabs. The request shape is compatible with OpenAI-style clients, but the server does not implement full OpenAI speech behavior — only the `input` field is used for synthesis. All other parameters (voice, model, format) are controlled server-side via environment variables.

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

- **Server-side config**: Output format is controlled by environment variables. Client-sent `response_format`, `speed`, `instructions`, and `stream_format` fields are accepted for compatibility but ignored.
- **Voice resolution**: If `voice` in the request matches the ElevenLabs voice ID format (20-char alphanumeric, e.g. `21m00Tcm4TlvDq8ikWAM`), it is forwarded to ElevenLabs. Otherwise (e.g. OpenAI names like `alloy`) it is ignored and `ELEVENLABS_VOICE_ID` from env is used.
- **Model resolution**: If `model` in the request starts with `eleven_` (e.g. `eleven_multilingual_v2`), it is forwarded to ElevenLabs. Otherwise (e.g. OpenAI names like `tts-1`) it is ignored and `ELEVENLABS_MODEL_ID` from env is used.
- **API key resolution**: If the request includes an `Authorization: Bearer <key>` header, that key is used for the ElevenLabs API call. Otherwise falls back to `XI_API_KEY` from env. This allows per-request billing to different ElevenLabs accounts.
- **Input validation**: `input` is required, must be a non-empty string, max 4096 characters.
- **Output format**: Controlled by `DEFAULT_FORMAT` (ElevenLabs format) and `DEFAULT_CONTENT_TYPE` (HTTP response content type). Default is `pcm_24000` with `audio/wav` content type. Note: `pcm_24000` returns raw headerless PCM, not a valid WAV file.
- **Easter egg**: Voice `the-voice-in-your-head` returns a canned audio clip from `static/the_force.pcm` without calling ElevenLabs.
- **Request schema**: `schemas/openai-compatible-audio-speech-request.schema.json`

## Environment Variables (`.env`)

| Variable | Required | Description |
|---|---|---|
| `XI_API_KEY` | Yes | ElevenLabs API key |
| `ELEVENLABS_VOICE_ID` | Yes | Server-side voice ID. See [voices docs](https://elevenlabs.io/docs/api-reference/get-voices). |
| `ELEVENLABS_MODEL_ID` | No | Server-side model (defaults to `eleven_multilingual_v2`). See [available models](https://elevenlabs.io/docs/api-reference/get-models). |
| `DEFAULT_FORMAT` | No | ElevenLabs output format (default: `pcm_24000`) |
| `DEFAULT_CONTENT_TYPE` | No | Response content type (default: `audio/wav`) |
| `ALLOWED_IPS` | No | Comma-separated whitelist of IPs with unlimited access. When set, all other IPs are limited to `CHAR_LIMIT` characters. Unset = no limit. |
| `CHAR_LIMIT` | No | Max characters for non-whitelisted IPs (default: `2000`). Only active when `ALLOWED_IPS` is set. |

## Dependencies

Python 3.12, FastAPI, Uvicorn, httpx, python-dotenv. No requirements.txt — deps are installed directly in Dockerfile.
