# elevenlabs-openai-shim

An adapter that accepts an OpenAI-compatible `/v1/audio/speech` request shape and generates speech using [ElevenLabs](https://elevenlabs.io).

This project is request-shape compatible with OpenAI-style speech clients, but it does not implement full OpenAI speech behavior.

## Quick start

### Docker (recommended)

```bash
cp .env.example .env
# Edit .env with your ElevenLabs credentials
docker compose up -d
```

The service is now listening on `http://localhost:8881`.

### Local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn httpx python-dotenv

cp .env.example .env
# Edit .env with your ElevenLabs credentials

uvicorn elevenlabs_openai_shim_streaming:app --host 127.0.0.1 --port 8881
```

## Configuration

Set these in `.env`:

| Variable               | Required | Description |
|------------------------|---|---|
| `XI_API_KEY`           | Yes | ElevenLabs API key |
| `ELEVENLABS_VOICE_ID`  | Yes | Default voice ID See [voices docs](https://elevenlabs.io/docs/api-reference/get-voices). |
| `ELEVENLABS_MODEL_ID`  | No | Model ID (defaults to `eleven_multilingual_v2`). See [available models](https://elevenlabs.io/docs/api-reference/get-models) |
| `ALLOWED_IPS`          | No | Comma-separated whitelist of IPs with unlimited access. When set, all other IPs are limited to `CHAR_LIMIT` characters. Unset = no limit. |
| `CHAR_LIMIT`           | No | Max characters for non-whitelisted IPs (default: `2000`). Only active when `ALLOWED_IPS` is set. |
| `DEFAULT_FORMAT`       | No | ElevenLabs output format. Default: `pcm_24000` |
| `DEFAULT_CONTENT_TYPE` | No | 	Response content type. Default: `audio/wav` |

## Usage
Request schema: `schemas/openai-compatible-audio-speech-request.schema.json`

The endpoint accepts an OpenAI-compatible request shape.

Only `input` is used for speech synthesis. Other request fields may be accepted for compatibility, but are ignored unless explicitly documented otherwise.

```bash
curl -X POST http://localhost:8881/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input": "Hello world"}' \
  --output speech.audio
```

### Authentication

The server uses the ElevenLabs API key from the `XI_API_KEY` environment variable by default. To override this per-request, pass your own key via the `Authorization` header:

```
Authorization: Bearer <your-elevenlabs-api-key>
```

This is compatible with OpenAI client libraries that send a Bearer token. When provided, the request is billed to the key owner's ElevenLabs account instead of the server default.

### Request body
| Field             | Type | Description                   |
|-------------------|---|-------------------------------|
| `input`           | string | Text to synthesize. Required. This is the only field used for synthesis. |
| `voice`           | string or object | Accepted for compatibility. If the value matches the ElevenLabs voice ID format (20-char alphanumeric, e.g. `21m00Tcm4TlvDq8ikWAM`), it is used as the voice for synthesis. Otherwise ignored (e.g. OpenAI names like `alloy`). Special value `the-voice-in-your-head` triggers the easter egg. |
| `model`           | string | If the value matches an ElevenLabs model ID (e.g. `eleven_multilingual_v2`), it is used for synthesis. Otherwise ignored (e.g. OpenAI names like `tts-1`). See [available models](https://elevenlabs.io/docs/api-reference/get-models). |
| `response_format` | string | Accepted for compatibility. Ignored by this server. |
| `instructions`    | string | Accepted for compatibility. Ignored by this server. |
| `speed`           | number | Accepted for compatibility. Ignored by this server. |
| `stream_format`   | string | Accepted for compatibility. Ignored by this server. |

### Endpoints

- `POST /v1/audio/speech` — Synthesize speech
- `GET /health` — Service health check

## Variants

The repo includes two implementations:

- **`elevenlabs_openai_shim_streaming.py`** — Streams audio chunks back to the client as they are generated. Lower time-to-first-byte. **This is the default used by Docker.**
- **`elevenlabs_openai_shim.py`** — Buffers the full audio response before returning. Simpler, but higher latency.

## Easter egg

If `voice` is set to `the-voice-in-your-head` the shim returns a canned audio clip instead of calling ElevenLabs..

```bash
curl -X POST http://localhost:8881/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input": "anything", "voice": "the-voice-in-your-head"}' \
  --output the_force.audio
```

## Audio format note
The audio response format is controlled by server-side configuration.

When `DEFAULT_FORMAT=pcm_24000`, ElevenLabs returns raw headerless PCM audio (24 kHz, 16-bit, mono). This is not a real WAV file, even if the response content type is set to `audio/wav`, because no RIFF/WAV header is included.

Clients that require a proper WAV file must wrap the PCM stream in a WAV container themselves, or the server must be changed to do so.

## License

MIT
