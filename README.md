# cAIru Base Station

**A local-first voice companion for seniors with dementia.**

cAIru is a wellness companion that provides conversation and proactive check-ins for seniors. This repository contains the Base Station software that runs on an Intel N100 mini-PC.

## 🏗️ Architecture

```
Companion Device (mic/speaker)
        │
        │ WebSocket (audio)
        ▼
┌─────────────────────────────────────────────┐
│              BASE STATION                   │
│                                             │
│  Gateway → VAD → ASR → Orchestrator → LLM   │
│     ↑                                  │    │
│     └──────────── TTS ←────────────────┘    │
│                                             │
│  [Redis Streams]  [Ollama]  [SQLite]        │
└─────────────────────────────────────────────┘
```

### Services

| Service | Purpose | Technology |
|---------|---------|------------|
| **gateway** | WebSocket for Companion | FastAPI |
| **vad** | Voice Activity Detection | Silero VAD |
| **asr** | Speech-to-Text | Faster-Whisper |
| **orchestrator** | State, memory, rules | SQLite |
| **llm** | Response generation | Ollama (Phi-3) |
| **tts** | Text-to-Speech | Piper |

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- macOS or Linux

### Setup

```bash
# Run setup script
./scripts/setup_dev.sh

# Start development environment
make dev
```

### Test Connection

```bash
# With services running
python scripts/test_pipeline.py
```

### Access

- **WebSocket**: `ws://localhost:8080/ws`
- **Health Check**: `http://localhost:8080/health`

## 📁 Project Structure

```
calru-companion-ai/
├── services/
│   ├── gateway/        # WebSocket entry point
│   ├── vad/            # Voice Activity Detection
│   ├── asr/            # Speech Recognition
│   ├── orchestrator/   # Central brain
│   ├── llm/            # Language model
│   └── tts/            # Text-to-Speech
├── shared/             # Common library
├── config/             # Rules, Prometheus
├── scripts/            # Setup, deploy
├── docker-compose.yml  # Production config
└── Makefile            # Dev commands
```

## 🛠️ Development

### Commands

```bash
make dev        # Start with hot-reload
make up         # Start production mode
make down       # Stop all
make logs       # Follow logs
make logs-llm   # Specific service logs
```

### Running Services Individually

```bash
# Start infrastructure only
docker compose up -d redis ollama

# Activate venv and run a service
source venv/bin/activate
cd services/orchestrator && python -m src.main
```

## 🚢 Deploy to N100

```bash
export N100_HOST=192.168.1.x
make deploy
```

## 🔧 Configuration

Copy `env.example` to `.env`:

```bash
# LLM
LLM_MODEL=phi3:mini

# ASR
WHISPER_MODEL=small.en

# TTS
PIPER_VOICE=en_US-lessac-medium
```

## 📊 Latency Target

| Stage | Target |
|-------|--------|
| VAD | 10ms |
| ASR | 300ms |
| LLM | 350ms |
| TTS | 50ms |
| **Total** | **<800ms** |

## 📚 Docs

- [ARCHITECTURE.md](ARCHITECTURE.md) — System design

---

*Built for seniors and their caregivers* 🦉
