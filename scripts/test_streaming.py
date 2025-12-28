#!/usr/bin/env python3
"""
Streaming test client for cAIru Base Station.

Streams audio continuously to the server - server-side VAD detects speech boundaries.
This reduces latency by starting processing the moment speech ends.

Usage:
    python scripts/test_streaming.py
    python scripts/test_streaming.py --gateway ws://192.168.1.x:8080/ws

Requirements:
    pip install websockets sounddevice numpy
"""

import argparse
import asyncio
import base64
import json
import sys
import time

try:
    import numpy as np
    import sounddevice as sd
except ImportError:
    print("Missing dependencies. Install with:")
    print("  pip install sounddevice numpy")
    sys.exit(1)

try:
    import websockets
except ImportError:
    print("Missing websockets. Install with:")
    print("  pip install websockets")
    sys.exit(1)


# Audio settings - match server expectations
SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = np.int16
CHUNK_DURATION_MS = 100  # Send chunks every 100ms
CHUNK_SIZE = int(SAMPLE_RATE * CHUNK_DURATION_MS / 1000)


class StreamingClient:
    """Client that streams audio continuously to server."""
    
    def __init__(self, gateway_url: str):
        self.gateway_url = gateway_url
        self.is_playing = False
        self._stop_event = asyncio.Event()
    
    async def run(self):
        """Main loop - stream audio and receive responses."""
        print("🦉 cAIru Streaming Client (Server-side VAD)")
        print("=" * 50)
        print(f"Gateway: {self.gateway_url}")
        print("\n🎤 Streaming audio... (speak naturally, Ctrl+C to quit)\n")
        
        audio_queue = asyncio.Queue()
        
        def audio_callback(indata, frames, time_info, status):
            if status:
                print(f"Audio status: {status}")
            if not self.is_playing:
                audio_queue.put_nowait(indata.copy())
        
        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=CHUNK_SIZE,
            callback=audio_callback,
        )
        
        try:
            async with websockets.connect(
                self.gateway_url,
                max_size=10 * 1024 * 1024,
                ping_interval=None,
            ) as ws:
                print("📡 Connected to gateway\n")
                
                with stream:
                    # Run sender and receiver concurrently
                    await asyncio.gather(
                        self._send_audio(ws, audio_queue),
                        self._receive_responses(ws),
                    )
                    
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
        except Exception as e:
            print(f"\n❌ Error: {e}")
    
    async def _send_audio(self, ws, audio_queue: asyncio.Queue):
        """Continuously send audio chunks to server."""
        while not self._stop_event.is_set():
            try:
                chunk = await asyncio.wait_for(audio_queue.get(), timeout=0.5)
                
                # Skip if playing response
                if self.is_playing:
                    continue
                
                # Send as streaming chunk (server does VAD)
                audio_bytes = chunk.flatten().tobytes()
                
                # Send with streaming flag
                message = {
                    "type": "audio_stream",
                    "audio": base64.b64encode(audio_bytes).decode("utf-8"),
                    "is_streaming": True,
                }
                await ws.send(json.dumps(message))
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"Send error: {e}")
                break
    
    async def _receive_responses(self, ws):
        """Receive and play responses from server."""
        while not self._stop_event.is_set():
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=1.0)
                
                if isinstance(response, str):
                    data = json.loads(response)
                    text = data.get('text', '')
                    
                    if text:
                        print(f"\n📥 Response: \"{text}\"")
                    
                    if 'audio' in data:
                        audio_bytes = base64.b64decode(data['audio'])
                        print(f"🔊 Playing ({len(audio_bytes)} bytes)...")
                        await self._play_audio(audio_bytes)
                        print("✅ Done\n🎤 Listening...")
                        
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                if "close" not in str(e).lower():
                    print(f"Receive error: {e}")
                break
    
    async def _play_audio(self, audio_data: bytes):
        """Play audio response."""
        self.is_playing = True
        try:
            if audio_data[:4] == b'RIFF':
                import wave
                import io
                wav_io = io.BytesIO(audio_data)
                with wave.open(wav_io, 'rb') as wav:
                    sr = wav.getframerate()
                    frames = wav.readframes(wav.getnframes())
                    audio_array = np.frombuffer(frames, dtype=np.int16)
            else:
                sr = 22050
                audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            sd.play(audio_array, sr)
            sd.wait()
        finally:
            self.is_playing = False


def main():
    parser = argparse.ArgumentParser(description="Streaming test client (server-side VAD)")
    parser.add_argument(
        "--gateway",
        default="ws://localhost:8080/ws",
        help="Gateway WebSocket URL",
    )
    args = parser.parse_args()
    
    client = StreamingClient(args.gateway)
    
    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")


if __name__ == "__main__":
    main()

