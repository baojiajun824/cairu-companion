# cAIru Base Station

**A local-first voice companion for seniors with dementia.**

cAIru is a wellness companion that provides conversation and proactive check-ins for seniors. This repository contains the Base Station software that runs on an Intel N100 mini-PC.

## 🏗️ Architecture

```
Your Mac/iPhone (mic/speaker)
        │
        │ WiFi (WebSocket)
        ▼
┌─────────────────────────────────────────────────────┐
│                   N100 BASE STATION                  │
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

---

## 🚀 Quick Start (N100 Server)

### Prerequisites

- Intel N100 mini-PC (or any Linux machine)
- Docker & Docker Compose installed
- Connected to your home WiFi

### Step 1: Clone & Start

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/cairu-companion.git
cd cairu-companion

# Start all services (this takes 2-3 minutes first time)
docker compose up -d

# Wait for everything to be ready
docker compose ps
```

You should see all services as "healthy":
```
NAME              STATUS
cairu-asr         Up (healthy)
cairu-gateway     Up (healthy)
cairu-llm         Up (healthy)
cairu-ollama      Up (healthy)
cairu-orchestrator Up (healthy)
cairu-redis       Up (healthy)
cairu-tts         Up (healthy)
cairu-vad         Up (healthy)
```

### Step 2: Download AI Model (First Time Only)

```bash
docker compose exec ollama ollama pull qwen2:0.5b
```

This downloads the language model (~400MB). Only needed once.

### Step 3: Find Your N100's IP Address

```bash
hostname -I | awk '{print $1}'
```

Write down this IP address (e.g., `192.168.1.50`). You'll need it to connect from your Mac.

### Step 4: Test Connection

On your Mac (or any computer on the same WiFi):

```bash
curl http://192.168.1.50:8080/health
```

Should return `{"status":"healthy"}`.

---

## 🎤 Test a Conversation (Step-by-Step)

This guide walks you through having a voice conversation with cAIru. You'll need:
- **N100** running the server (on your home network)
- **Mac** to talk to cAIru (on the same network)

### 📍 On the N100 (Server)

**1. Make sure the server is running:**
```bash
cd cairu-companion
docker compose up -d
```

**2. Check everything is healthy:**
```bash
docker compose ps
```
All services should show "Up (healthy)".

**3. Get the N100's IP address:**
```bash
hostname -I | awk '{print $1}'
```
Example output: `192.168.1.50` — write this down!

---

### 💻 On Your Mac (Client)

**1. One-time setup** (only do this once):
```bash
cd cairu-companion
python3 -m venv .venv
source .venv/bin/activate
pip install websockets sounddevice numpy
```

**2. Start the voice client:**
```bash
cd cairu-companion
source .venv/bin/activate
python scripts/test_streaming.py --gateway ws://192.168.1.50:8080/ws
```
*(Replace `192.168.1.50` with your N100's actual IP)*

**3. Start talking!**

You'll see:
```
🎙️  Streaming Client (Server-side VAD)
🔗 Connecting to ws://192.168.1.50:8080/ws...
✅ Connected!
🎤 Listening... (speak naturally, pause when done)
```

**4. Have a conversation:**
- Say: *"Hello, how are you?"*
- Wait 5-8 seconds for the response
- Listen to cAIru's reply through your speakers
- Continue the conversation!

**5. To stop:** Press `Ctrl+C`

---

### 🔄 What Happens During a Conversation

```
You speak → Mac mic captures audio
                ↓
        WiFi sends to N100
                ↓
    N100 detects you stopped speaking (VAD)
                ↓
    N100 converts speech to text (ASR)
                ↓
    N100 generates a response (LLM)
                ↓
    N100 converts text to speech (TTS)
                ↓
        WiFi sends back to Mac
                ↓
Mac speakers play the response ← You hear cAIru
```

Total time: **5-8 seconds** per response.

---

### 🔄 Start Fresh (Clear Memory)

If cAIru remembers old conversations and you want to start over:

**On N100:**
```bash
docker compose exec orchestrator rm -f /app/data/cairu.db
docker compose restart orchestrator
```

Then restart your test client on Mac.

---

## 📱 Testing from iPhone

**Option A: Use Mac as Bridge** (Recommended)
- Run the test client on your Mac
- Speak into Mac's microphone

**Option B: AirPlay Microphone**
- Use iPhone as microphone input to Mac
- Mac runs the test client

**Option C: Future Web Client**
- A web-based client is planned for Safari

---

## 🛠️ Managing the Server

### Common Commands (Run on N100)

```bash
# Start server
docker compose up -d

# Stop server
docker compose down

# View logs (all services)
docker compose logs -f

# View specific service logs
docker compose logs -f llm
docker compose logs -f gateway

# Check service health
docker compose ps

# Restart a service
docker compose restart llm
```

### Clear Conversation History

If the AI remembers old conversations and you want to start fresh:

```bash
docker compose exec orchestrator rm -f /app/data/cairu.db
docker compose restart orchestrator
```

### Update to Latest Version

```bash
git pull
docker compose down
docker compose build
docker compose up -d
```

---

## ⚡ Performance

### Expected Latency

| Component | Time |
|-----------|------|
| VAD (voice detection) | ~50ms |
| ASR (speech-to-text) | ~800-1200ms |
| LLM (response generation) | ~3-6 seconds |
| TTS (text-to-speech) | ~200-400ms |
| **Total** | **~5-8 seconds** |

*Note: LLM is the bottleneck on CPU-only hardware. Responses stream sentence-by-sentence for faster perceived latency.*

### Optimizations Enabled

| Feature | Status |
|---------|--------|
| Streaming LLM output | ✅ |
| Sentence-level TTS | ✅ |
| Fast TTS voice | ✅ |
| Server-side VAD | ✅ |
| Smallest models | ✅ |

---

## 🔧 Troubleshooting

### "Connection refused" from Mac

1. Check N100 is running: `docker compose ps`
2. Check firewall allows port 8080
3. Verify IP address: `hostname -I`

### Services show "unhealthy"

```bash
# Check which service is failing
docker compose ps

# View that service's logs
docker compose logs llm

# Restart it
docker compose restart llm
```

### AI gives weird/repeated responses

Clear the conversation history:
```bash
docker compose exec orchestrator rm -f /app/data/cairu.db
docker compose restart orchestrator
```

### No audio plays on Mac

1. Check Mac microphone permissions (System Settings → Privacy → Microphone)
2. Check speaker volume
3. Verify audio devices: `python -c "import sounddevice; print(sounddevice.query_devices())"`

---

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
├── shared/             # Common library
├── scripts/
│   └── test_streaming.py  # Voice test client
├── docker-compose.yml  # Server configuration
└── ARCHITECTURE.md     # Technical details
```

---

## 📚 Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — Detailed technical design

---

*Built for seniors and their caregivers* 🦉
