# speech — Voice Services (STT + TTS)

Two OpenAI-compatible voice services that give the AI stack ears and a voice,
primarily through Open WebUI's chat interface:

| Service | Engine | Host port | Endpoint |
| --- | --- | --- | --- |
| `speech-stt` | [speaches](https://github.com/speaches-ai/speaches) (faster-whisper) | 8091 | `/v1/audio/transcriptions` |
| `speech-tts` | [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI) (Kokoro-82M) | 8093 | `/v1/audio/speech` |

Both run **CPU-only on purpose** — Whisper-small and Kokoro (82M parameters)
are fast enough on CPU, and this keeps the GPU's VRAM free for the LLMs
(see the model hierarchy in [README.md](../README.md)).

---

## Attribution

**speaches** is open-source software developed and maintained by the [speaches contributors](https://github.com/speaches-ai/speaches/graphs/contributors), made freely available under the [MIT License](https://github.com/speaches-ai/speaches/blob/master/LICENSE). It builds on [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT) and OpenAI's open-source [Whisper](https://github.com/openai/whisper) models (MIT).

**Kokoro-FastAPI** is open-source software developed and maintained by the [Kokoro-FastAPI contributors](https://github.com/remsky/Kokoro-FastAPI/graphs/contributors), made freely available under the [Apache 2.0 License](https://github.com/remsky/Kokoro-FastAPI/blob/master/LICENSE). The underlying [Kokoro-82M model](https://huggingface.co/hexgrad/Kokoro-82M) is released under the Apache 2.0 License.

---

## Setup

### Start

```bash
./start.sh
```

On first run this copies `.env.example` → `.env` (no secrets to generate),
pulls both images, and starts the containers. The first STT request
downloads the Whisper model from Hugging Face into `./data/speech/stt`
(~500 MB for `small`); Kokoro's voice model ships in the image.

### Wire into Open WebUI

**Admin Settings → Audio** (UI-side config — Open WebUI stores it in its
database; recreate from here after a reset):

- **Speech-to-Text**: engine `OpenAI`, URL
  `http://host.docker.internal:8091/v1`, API key `no-key`, model
  `Systran/faster-whisper-small`.
- **Text-to-Speech**: engine `OpenAI`, URL
  `http://host.docker.internal:8093/v1`, API key `no-key`, voice
  `af_heart`.

Then in a chat: microphone button to dictate, speaker icon on a reply to
hear it.

---

## Local Access

| | |
| --- | --- |
| **STT API** | <http://localhost:8091/v1/audio/transcriptions> |
| **TTS API** | <http://localhost:8093/v1/audio/speech> |
| **Via name-proxy** | <http://stt.localhost>, <http://tts.localhost> |

### Smoke tests

```bash
# STT — transcribe a WAV file
curl -s http://localhost:8091/v1/audio/transcriptions \
  -F file=@sample.wav -F model=Systran/faster-whisper-small

# TTS — synthesize speech
curl -s http://localhost:8093/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"model":"kokoro","input":"Hello from the maker ops stack.","voice":"af_heart"}' \
  -o out.wav
```

### Tuning

- **STT accuracy vs speed**: the model is chosen per-request by the client.
  In Open WebUI, switch the STT model field to
  `Systran/faster-whisper-base` (faster) or `...-medium` / `...-large-v3`
  (more accurate, noticeably slower on CPU).
- **TTS voices**: Kokoro ships 50+ voices across 8 languages —
  `GET http://localhost:8093/v1/audio/voices` lists them.

---

## Files

| File | Purpose |
| --- | --- |
| `docker-compose.yml` | Two-container stack definition (stt + tts) |
| `.env.example` | Configuration template |
| `start.sh` | Pull images and start |
| `stop.sh` | Stop (model cache preserved) |
| `teardown.sh` | Full wipe with confirmation |

---

## Architecture

```text
Open WebUI (Admin Settings → Audio)
  ├─► host.docker.internal:8091/v1  → speech-stt  (speaches, CPU)
  │         └─► ./data/speech/stt  (Whisper model cache, downloaded on first use)
  └─► host.docker.internal:8093/v1  → speech-tts  (Kokoro-FastAPI, CPU)

Browser (direct API use)
  ├─► localhost:8091  /  stt.localhost  (via name-proxy)
  └─► localhost:8093  /  tts.localhost  (via name-proxy)
```

---

## Cheat Sheet

### Logs

```bash
docker compose -p speech logs -f
```

### Upgrade

```bash
./stop.sh && ./start.sh   # start.sh always pulls latest images
```
