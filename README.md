# cAIru Base Station

**A local-first voice companion for seniors with dementia.**

cAIru is a wellness companion that provides conversation and proactive check-ins for seniors. This repository contains the Base Station software that runs on an Intel N100 mini-PC.

## 🏗️ Architecture

```
Companion Device / Test Client (mic/speaker)
        │
        │ WebSocket (audio stream)
        ▼
┌─────────────────────────────────────────────────────┐
│                   BASE STATION                       │
│                                                      │
│  Gateway → VAD → ASR → Orchestrator → LLM → TTS     │
│     ↑                                      │        │
│     └──────────────────────────────────────┘        │
│                                                      │
│  [Redis Streams]  [Ollama]  [SQLite]                │
└─────────────────────────────────────────────────────┘
```

### Services

| Service | Purpose | Technology |
|---------|---------|------------|
| **gateway** | WebSocket audio streaming | FastAPI |
| **vad** | Voice Activity Detection | Silero VAD / Energy-based |
| **asr** | Speech-to-Text | Faster-Whisper (tiny.en) |
| **orchestrator** | State, memory, rules | SQLite |
| **llm** | Response generation | Ollama (qwen2:0.5b) |
| **tts** | Text-to-Speech | Piper (lessac-low) |

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- macOS or Linux

### Setup

```bash
# Clone and enter directory
cd cairu-companion

# Create Python virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install websockets sounddevice numpy

# Start all services
docker compose up -d

# Wait for services to be healthy (~60s for model downloads)
docker compose ps
```

### Test with Microphone

```bash
# Start the test client (streams audio, server does VAD)
python scripts/test_streaming.py

# Test against remote N100
python scripts/test_streaming.py --gateway ws://N100-IP:8080/ws
```

### Access Points

- **WebSocket**: `ws://localhost:8080/ws`
- **Health Check**: `http://localhost:8080/health`

## 📁 Project Structure

```
cairu-companion/
├── services/
│   ├── gateway/        # WebSocket entry point
│   ├── vad/            # Voice Activity Detection
│   ├── asr/            # Speech Recognition  
│   ├── orchestrator/   # Central brain
│   ├── llm/            # Language model
│   └── tts/            # Text-to-Speech
├── shared/             # Common library (cairu_common)
├── config/             # Rules, Prometheus config
├── scripts/            # Test clients, deploy scripts
├── docker-compose.yml  # Production config
└── Makefile            # Dev commands
```

## 🛠️ Development

### Commands

```bash
docker compose up -d      # Start all services
docker compose down       # Stop all
docker compose logs -f    # Follow logs
docker compose logs llm   # Specific service logs
docker compose ps         # Check health status
```

### Clear Conversation History

```bash
docker compose exec orchestrator rm -f /app/data/cairu.db
docker compose restart orchestrator
```

## 🚢 Deploy to N100

```bash
# Copy project to N100
scp -r . user@n100-ip:/opt/cairu-companion

# SSH and start
ssh user@n100-ip
cd /opt/cairu-companion
docker compose up -d
```

## 📱 Connecting from iPhone/Mobile

Options for sending audio to the Base Station:

1. **Web Client** (Recommended): Open `http://n100-ip:8080` in Safari
2. **Test from Mac**: Run `python scripts/test_continuous.py --gateway ws://n100-ip:8080/ws`
3. **Custom iOS App**: Build with WebSocket audio streaming

## 🔧 Configuration

Environment variables in `docker-compose.yml`:

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_MODEL` | qwen2:0.5b | Ollama model (fastest) |
| `WHISPER_MODEL` | tiny.en | ASR model size |
| `PIPER_VOICE` | en_US-lessac-low | TTS voice |

## ⚡ Performance Optimizations

| Optimization | Status | Impact |
|--------------|--------|--------|
| Ollama streaming | ✅ | Faster token delivery |
| Sentence-level TTS | ✅ | First sentence plays faster |
| Fast TTS voice | ✅ | ~200ms saved |
| Server-side VAD | ✅ | Boundary detection |

### Expected Latency (N100)

| Component | Latency |
|-----------|---------|
| VAD | ~50ms |
| ASR | ~800-1200ms |
| LLM | ~3-6 seconds |
| TTS | ~200-400ms |
| **Total** | **~5-8 seconds** |

*Note: LLM is the bottleneck on CPU-only hardware.*

## 📚 Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — Detailed system design

---

*Built for seniors and their caregivers* 🦉
