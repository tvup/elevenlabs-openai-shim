# elevenlabs-openai-shim

An adapter that exposes an OpenAI-compatible `/v1/audio/speech` endpoint backed by [ElevenLabs](https://elevenlabs.io) TTS. Drop it in front of any client that speaks the OpenAI speech API and get ElevenLabs voices without changing a line of client code.

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

| Variable | Required | Description |
|---|---|---|
| `XI_API_KEY` | Yes | ElevenLabs API key |
| `ELEVENLABS_VOICE_ID` | Yes | Default voice ID (used when request omits `voice`) |
| `ELEVENLABS_MODEL_ID` | No | Model ID (defaults to `eleven_multilingual_v2`). See [available models](https://elevenlabs.io/docs/api-reference/get-models) |

## Usage

```bash
curl -X POST http://localhost:8881/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input": "Hello world", "voice": "optional-voice-id"}' \
  --output speech.wav
```

### Request body

| Field | Type | Description |
|---|---|---|
| `input` | string | Text to synthesize (required) |
| `voice` | string | ElevenLabs voice ID (falls back to `ELEVENLABS_VOICE_ID`). See [voices docs](https://elevenlabs.io/docs/api-reference/get-voices). Use `the-voice-in-your-head` for a built-in easter egg |
| `model` | string | ElevenLabs model ID (falls back to `ELEVENLABS_MODEL_ID`). See [available models](https://elevenlabs.io/docs/api-reference/get-models) |
| `response_format` | string | `mp3` or `wav` |
| `format` | string | Alternative to `response_format` |

### Endpoints

- `POST /v1/audio/speech` — Synthesize speech
- `GET /health` — Service health check

## Variants

The repo includes two implementations:

- **`elevenlabs_openai_shim_streaming.py`** — Streams audio chunks back to the client as they are generated. Lower time-to-first-byte. **This is the default used by Docker.**
- **`elevenlabs_openai_shim.py`** — Buffers the full audio response before returning. Simpler, but higher latency.

## Easter egg

Set `voice` to `the-voice-in-your-head` and the shim returns a canned audio clip saying "The Force" instead of calling ElevenLabs. No API key needed.

```bash
curl -X POST http://localhost:8881/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input": "anything", "voice": "the-voice-in-your-head"}' \
  --output the_force.wav
```

## Audio format note

When the output format is `wav`, ElevenLabs returns raw headerless PCM (`pcm_24000`: 24 kHz, 16-bit, mono) — not a standard WAV file with RIFF headers. MP3 output (`mp3_44100_128`) is a standard self-contained file.

The `PINNED_FORMAT` constant in both Python files is set to `"wav"` by default, which overrides any client-requested format. Set it to `None` in the source to let clients choose.

## License

MIT
