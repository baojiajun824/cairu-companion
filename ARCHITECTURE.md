# cAIru Base Station Architecture

## Overview

cAIru is a voice-based wellness companion for seniors with dementia. The system consists of two physical components:

1. **Companion** — A portable "owl" device with mic, speaker, and small display (out of scope for Alpha)
2. **Base Station** — Intel N100 mini-PC running the core intelligence pipeline

This document describes the Base Station architecture for the Alpha build.

---

## System Goals

| Goal | Description |
|------|-------------|
| **Local-First** | All functionality runs without internet |
| **Low Latency** | Target <1s, realistic ~5-8s on N100 |
| **Simple** | Single device, single user, minimal complexity |
| **Observable** | Comprehensive logging and metrics |

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CLIENT (Mac/iPhone/Companion)                        │
│                              (mic, speaker)                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ Audio Stream (WebSocket over WiFi)
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                               BASE STATION (N100)                            │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                         GATEWAY SERVICE                               │   │
│  │                   (WebSocket at ws://IP:8080/ws)                      │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                      │                                       │
│                                      ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                         REDIS STREAMS                                 │   │
│  │                     (message bus between services)                    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│         │              │              │              │              │        │
│         ▼              ▼              ▼              ▼              ▼        │
│  ┌──────────┐   ┌──────────┐   ┌──────────────┐   ┌──────────┐   ┌────────┐ │
│  │   VAD    │ → │   ASR    │ → │ ORCHESTRATOR │ → │   LLM    │ → │  TTS   │ │
│  │  Silero  │   │ Whisper  │   │    State     │   │  Ollama  │   │ Piper  │ │
│  │ (10ms)   │   │ (1000ms) │   │   (50ms)     │   │ (3-6s)   │   │(300ms) │ │
│  └──────────┘   └──────────┘   └──────────────┘   └──────────┘   └────────┘ │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                         DATA STORES                                   │   │
│  │                                                                       │   │
│  │   SQLite (conversations, profiles)    Ollama (LLM models)            │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Pipeline Flow

### Reactive Flow (User Speaks)

```
1. Client streams audio continuously to Gateway via WebSocket
2. Gateway → VAD: Voice activity detection (server-side)
3. VAD detects speech boundaries (start/end of utterance)
4. If complete utterance detected:
   a. VAD → ASR: Transcribe speech to text
   b. ASR → Orchestrator: Build context + prompt
   c. Orchestrator → LLM: Generate response (streaming)
   d. LLM → TTS: Each sentence streamed individually
   e. TTS → Gateway: Audio for each sentence
   f. Gateway → Client: Playback (sentence by sentence)
```

### Key Optimization: Sentence Streaming

Instead of waiting for the full LLM response, we:
1. Stream LLM output token-by-token
2. Detect sentence boundaries (., !, ?)
3. Send each complete sentence to TTS immediately
4. Client plays first sentence while LLM generates the rest

This reduces perceived latency from ~8s to ~5s.

---

## Service Descriptions

### Gateway Service
- **Purpose**: Entry point for client devices
- **Protocol**: WebSocket at `/ws`
- **Responsibilities**:
  - Accept WebSocket connections
  - Handle both binary audio and JSON-wrapped base64 audio
  - Route responses back to clients
  - Health check at `/health`

### VAD Service (Voice Activity Detection)
- **Purpose**: Detect when user starts/stops speaking
- **Model**: Silero VAD (with energy-based fallback)
- **Responsibilities**:
  - Server-side speech boundary detection
  - Accumulate audio until utterance complete
  - Only forward complete utterances to ASR

### ASR Service (Automatic Speech Recognition)
- **Purpose**: Convert speech to text
- **Model**: Faster-Whisper `tiny.en` (~1s latency)
- **Responsibilities**:
  - Transcribe audio segments
  - Output text with confidence scores

### Orchestrator Service
- **Purpose**: Central brain of the system
- **Responsibilities**:
  - Conversation state management (SQLite)
  - User profile and memory
  - Build LLM prompts with context
  - Enforce response brevity

### LLM Service
- **Purpose**: Natural language generation
- **Model**: Ollama with `qwen2:0.5b` (fastest for CPU)
- **Responsibilities**:
  - Generate conversational responses
  - **Streaming**: Output sentences as they complete
  - Send each sentence directly to TTS

### TTS Service (Text-to-Speech)
- **Purpose**: Convert text to natural speech
- **Model**: Piper TTS `en_US-lessac-low`
- **Responsibilities**:
  - Synthesize audio for each sentence
  - Return audio to Gateway for playback

---

## Technology Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| **Language** | Python 3.11+ | Fast iteration, rich ML ecosystem |
| **Framework** | FastAPI | Async, WebSocket support |
| **Message Bus** | Redis Streams | Lightweight, persistent |
| **Database** | SQLite | Simple, local, no dependencies |
| **Containers** | Docker Compose | Isolation, reproducibility |
| **ASR** | Faster-Whisper tiny.en | Fastest for CPU |
| **LLM** | Ollama qwen2:0.5b | Smallest capable model |
| **TTS** | Piper lessac-low | Fast CPU inference |
| **VAD** | Silero VAD | Tiny, fast |

---

## Latency Analysis

### Measured on N100 (CPU-only)

| Stage | Latency | Notes |
|-------|---------|-------|
| Network (WiFi) | ~5ms | Local network, negligible |
| VAD | ~50ms | Energy-based detection |
| ASR | ~800-1200ms | Whisper tiny.en |
| Orchestrator | ~50ms | SQLite + prompt build |
| LLM (first sentence) | ~3-6s | qwen2:0.5b streaming |
| TTS | ~200-400ms | Piper low voice |
| **Total to first audio** | **~5-8s** | |

### Bottleneck Analysis

```
LLM inference: ████████████████████████████ 70%
ASR:           ██████████ 20%
TTS:           ███ 7%
Other:         █ 3%
```

**The LLM is the bottleneck.** Improving it requires:
- GPU acceleration (not available on N100)
- Cloud API fallback (adds latency, requires internet)
- Better local models (as they become available)

---

## Data Storage (SQLite)

```sql
-- User profile (single user for Alpha)
user_profiles: user_id, name, preferred_name, life_details, preferences

-- Conversation history
conversation_turns: session_id, role, content, timestamp

-- Care plan
care_plans: user_id, medications, routines, contacts

-- Learned facts (memory)
learned_facts: user_id, fact_type, fact_key, fact_value
```

Database location: `/app/data/cairu.db` (inside orchestrator container)

---

## Message Bus Topics (Redis Streams)

| Stream | Publisher | Consumer | Data |
|--------|-----------|----------|------|
| `cairu:audio:inbound` | Gateway | VAD | Raw audio chunks |
| `cairu:audio:segments` | VAD | ASR | Complete utterances |
| `cairu:text:transcripts` | ASR | Orchestrator | Transcribed text |
| `cairu:llm:requests` | Orchestrator | LLM | Prompt + context |
| `cairu:llm:responses` | LLM | Orchestrator | Full response |
| `cairu:tts:requests` | LLM | TTS | Each sentence |
| `cairu:audio:outbound` | TTS | Gateway | Audio + text |

---

## Configuration

### Models (in `shared/cairu_common/config.py`)

| Setting | Value | Notes |
|---------|-------|-------|
| `whisper_model` | `tiny.en` | Fastest ASR |
| `llm_model` | `qwen2:0.5b` | Fastest LLM for CPU |
| `piper_voice` | `en_US-lessac-low` | Fast TTS voice |

### Environment Variables

Set in `docker-compose.yml`:

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://redis:6379` | Redis connection |
| `OLLAMA_URL` | `http://ollama:11434` | Ollama API |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

---

## Network Architecture

```
┌─────────────┐         WiFi           ┌─────────────────┐
│   Client    │ ◄─────────────────────► │  N100 Base      │
│   (Mac)     │    ws://IP:8080/ws      │  Station        │
│             │                         │                 │
│   🎤 Mic    │    ~5ms latency         │   Docker        │
│   🔊 Speaker│    (local network)      │   Containers    │
└─────────────┘                         └─────────────────┘
```

**Why WiFi over Bluetooth?**
- WiFi: 1-5ms latency
- Bluetooth: 40-200ms latency (codec overhead)
- WiFi supports full duplex, higher bandwidth

---

## Project Structure

```
cairu-companion/
├── docker-compose.yml          # Service orchestration
├── Makefile                    # Common commands
│
├── services/
│   ├── gateway/               # WebSocket entry point
│   │   └── src/
│   │       ├── main.py        # FastAPI app
│   │       ├── websocket.py   # Connection manager
│   │       └── routing.py     # Audio routing
│   │
│   ├── vad/                   # Voice Activity Detection
│   │   └── src/
│   │       ├── main.py        # Service entry
│   │       └── detector.py    # Silero VAD wrapper
│   │
│   ├── asr/                   # Speech Recognition
│   │   └── src/
│   │       ├── main.py        # Service entry
│   │       └── transcriber.py # Whisper wrapper
│   │
│   ├── orchestrator/          # Central brain
│   │   └── src/
│   │       ├── main.py        # Service entry
│   │       ├── state.py       # SQLite state manager
│   │       └── prompts/       # LLM prompt templates
│   │
│   ├── llm/                   # Language model
│   │   └── src/
│   │       ├── main.py        # Service entry
│   │       ├── router.py      # Model selection
│   │       └── backends/      # Ollama backend
│   │
│   └── tts/                   # Text-to-Speech
│       └── src/
│           ├── main.py        # Service entry
│           └── synthesizer.py # Piper wrapper
│
├── shared/
│   └── cairu_common/          # Shared library
│       ├── config.py          # Centralized config
│       ├── models.py          # Pydantic models
│       ├── redis_client.py    # Redis wrapper
│       └── logging.py         # Structured logging
│
├── scripts/
│   └── test_streaming.py      # Voice test client
│
└── config/
    └── rules/                 # Proactive rule definitions
```

---

## Simplifications for Alpha

| Area | Simplification |
|------|----------------|
| **Devices** | Single device, no registration |
| **Users** | Single user, no auth |
| **Dashboard** | Not implemented |
| **Events** | Not implemented |
| **Cloud** | No cloud fallback |

---

## Future Considerations (Post-Alpha)

1. **GPU Acceleration**: Add support for Intel Arc GPU or external GPU
2. **Cloud Fallback**: Use OpenAI/Claude API when local LLM struggles
3. **Multi-device**: Support multiple companions per base station
4. **Caregiver Dashboard**: Web UI for care plan management
5. **Mobile App**: iOS/Android client for family members
6. **Wake Word**: "Hey Cairu" activation

---

*Last Updated: January 2026*
