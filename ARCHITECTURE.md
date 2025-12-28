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
| **Low Latency** | <800ms response time for simple conversational turns |
| **Simple** | Single device, single user, minimal complexity |
| **Observable** | Comprehensive logging and metrics |

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              COMPANION DEVICE                                │
│                    (mic, speaker, display — black box for Alpha)            │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ Audio Stream (WebSocket)
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                               BASE STATION                                   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                         GATEWAY SERVICE                               │   │
│  │                   (WebSocket, single device)                          │   │
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
│  └──────────┘   └──────────┘   └──────────────┘   └──────────┘   └────────┘ │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Pipeline Flow

### Reactive Flow (User Speaks)

```
1. Companion captures audio continuously
2. Audio streamed to Gateway via WebSocket (ws://basestation:8080/ws)
3. Gateway → VAD: Check for voice activity
4. If voice detected:
   a. VAD → ASR: Transcribe speech to text
   b. ASR → Orchestrator: Process with context
   c. Orchestrator → LLM: Generate response
   d. LLM → Orchestrator: Receive response
   e. Orchestrator → TTS: Convert to speech
   f. TTS → Gateway: Audio + metadata
   g. Gateway → Companion: Playback
```

### Proactive Flow (System Initiates)

```
1. Orchestrator runs scheduled rules (morning check-in, reminders, etc.)
2. Rule triggers → Orchestrator → LLM → TTS → Gateway → Companion
3. System awaits response (returns to reactive flow)
```

---

## Service Descriptions

### Gateway Service
- **Purpose**: Entry point for the Companion device
- **Protocol**: WebSocket at `/ws` (no auth for Alpha)
- **Responsibilities**:
  - Accept single device connection
  - Route audio to pipeline
  - Return responses with audio

### VAD Service (Voice Activity Detection)
- **Purpose**: Filter silence/noise from speech
- **Model**: Silero VAD (~2ms latency)
- **Responsibilities**:
  - Detect speech start/end
  - Only forward audio with speech

### ASR Service (Automatic Speech Recognition)
- **Purpose**: Convert speech to text
- **Model**: Faster-Whisper (small.en)
- **Responsibilities**:
  - Transcribe audio segments
  - Handle elderly speech patterns

### Orchestrator Service
- **Purpose**: Central brain of the system
- **Responsibilities**:
  - Conversation state management
  - User profile and memory
  - Proactive rules engine
  - LLM prompt construction

### LLM Service
- **Purpose**: Natural language generation
- **Model**: Ollama with qwen2:0.5b (fastest) or phi3:mini (better quality)
- **Responsibilities**:
  - Generate conversational responses
  - Sentence-level streaming to TTS
  - Fallback to static responses if needed

### TTS Service (Text-to-Speech)
- **Purpose**: Convert text to natural speech
- **Model**: Piper TTS (CPU-optimized)
- **Responsibilities**:
  - Synthesize warm, calming voice
  - Stream audio back to Gateway

---

## Technology Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| **Language** | Python 3.11+ | Fast iteration, rich ML ecosystem |
| **Framework** | FastAPI | Async, WebSocket support |
| **Message Bus** | Redis Streams | Lightweight, persistent |
| **Database** | SQLite | Simple, local, no dependencies |
| **Containers** | Docker Compose | Isolation, reproducibility |
| **ASR** | Faster-Whisper | Optimized for CPU |
| **LLM** | Ollama | Easy local model management |
| **TTS** | Piper | Fast CPU inference |
| **VAD** | Silero VAD | Tiny, fast |

---

## Latency Budget

### Target (Ideal Hardware)

| Stage | Target | Notes |
|-------|--------|-------|
| Audio transmission | 50ms | WebSocket, local network |
| VAD | 10ms | Energy-based or Silero |
| ASR | 300ms | Whisper streaming |
| Orchestrator | 20ms | State lookup, prompt build |
| LLM | 350ms | With GPU acceleration |
| TTS | 50ms | Piper streaming |
| **Total** | **780ms** | Meets target with GPU |

### Reality (N100 CPU-only)

| Stage | Actual | Notes |
|-------|--------|-------|
| VAD | ~50ms | Energy-based detection |
| ASR | ~800-1200ms | tiny.en model |
| Orchestrator | ~50ms | SQLite queries |
| LLM | ~3-6 seconds | qwen2:0.5b on CPU |
| TTS | ~200-400ms | Piper low voice |
| **Total** | **~5-8 seconds** | CPU bottleneck |

*Note: LLM inference is the bottleneck on CPU. GPU or cloud API would dramatically improve.*

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

---

## Message Bus Topics (Redis Streams)

| Stream | Publisher | Consumer |
|--------|-----------|----------|
| `cairu:audio:inbound` | Gateway | VAD |
| `cairu:audio:segments` | VAD | ASR |
| `cairu:text:transcripts` | ASR | Orchestrator |
| `cairu:llm:requests` | Orchestrator | LLM |
| `cairu:llm:responses` | LLM | Orchestrator |
| `cairu:tts:requests` | Orchestrator | TTS |
| `cairu:audio:outbound` | TTS | Gateway |

---

## Project Structure

```
cairu-base-station/
├── docker-compose.yml          # Service orchestration
├── docker-compose.dev.yml      # Development overrides
├── env.example                 # Environment template
├── Makefile                    # Common commands
│
├── services/
│   ├── gateway/               # WebSocket entry point
│   ├── vad/                   # Voice Activity Detection
│   ├── asr/                   # Speech Recognition
│   ├── orchestrator/          # Central brain, rules
│   ├── llm/                   # Language model
│   └── tts/                   # Text-to-Speech
│
├── shared/
│   └── cairu_common/          # Shared library
│
├── config/
│   └── rules/                 # Proactive rule definitions
│
└── scripts/
    ├── setup_dev.sh           # Developer setup
    └── deploy.sh              # N100 deployment
```

---

## Development Workflow

### Local Development (MacBook)

```bash
# Start infrastructure
docker compose up -d redis ollama

# Run services locally
cd services/orchestrator && python -m src.main

# Or run everything
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

### Deployment to N100

```bash
./scripts/deploy.sh 192.168.1.x
```

---

## Simplifications for Alpha

| Area | Simplification |
|------|----------------|
| **Devices** | Single device, hardcoded ID |
| **Users** | Single user, no auth |
| **Dashboard** | Not implemented |
| **Events** | Not implemented |
| **Cloud** | No cloud fallback, local only |

---

## Connecting to Base Station

### From Mac/PC (Testing)

```bash
# Set gateway to N100 IP
python scripts/test_continuous.py --gateway ws://192.168.1.x:8080/ws
```

### From iPhone/Mobile

**Option 1: Web Client** (Easiest)
- Build a simple HTML5 web page with WebSocket + Web Audio API
- Host on N100, access via `http://192.168.1.x:8080`
- Works in Safari/Chrome

**Option 2: Native iOS App**
- Use URLSessionWebSocketTask for WebSocket
- AVAudioEngine for recording/playback
- Send audio as binary or base64 JSON

**Option 3: Bluetooth (Not Recommended)**
- Requires custom BLE audio profile
- Complex setup, not standard
- Better to use WiFi/WebSocket

---

## Future Considerations (Post-Alpha)

1. **Multi-device support**: Device registration and routing
2. **Caregiver dashboard**: Events, alerts, care plan management
3. **Cloud fallback**: OpenAI as backup when local LLM struggles
4. **Authentication**: Device pairing, user management
5. **Mobile companion app**: iOS/Android client for testing

---

*Last Updated: December 2025*
