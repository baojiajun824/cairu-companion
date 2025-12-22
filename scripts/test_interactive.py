#!/usr/bin/env python3
"""
Interactive test client for cAIru Base Station.

Records audio from microphone, sends to gateway, and plays back the response.

Usage:
    python scripts/test_interactive.py [--gateway ws://localhost:8080/ws]

Requirements:
    pip install websockets sounddevice numpy
"""

import argparse
import asyncio
import base64
import json
import struct
import sys
import threading
import time
from queue import Queue

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


# Audio settings (must match what the pipeline expects)
SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = np.int16


def record_audio(duration_seconds: float = 3.0) -> bytes:
    """Record audio from the microphone."""
    print(f"\n🎤 Recording for {duration_seconds} seconds... Speak now!")
    
    # Record audio
    frames = int(duration_seconds * SAMPLE_RATE)
    recording = sd.rec(frames, samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=DTYPE)
    sd.wait()
    
    print("✅ Recording complete!")
    
    # Convert to bytes (16-bit PCM)
    return recording.tobytes()


def play_audio(audio_data: bytes, sample_rate: int = 22050):
    """Play audio from bytes."""
    # Detect format - check for WAV header
    if audio_data[:4] == b'RIFF':
        # Parse WAV header to get actual sample rate
        import wave
        import io
        wav_io = io.BytesIO(audio_data)
        with wave.open(wav_io, 'rb') as wav:
            sample_rate = wav.getframerate()
            n_channels = wav.getnchannels()
            audio_data = wav.readframes(wav.getnframes())
            # Convert to numpy
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            if n_channels == 2:
                audio_array = audio_array.reshape(-1, 2)
    else:
        # Assume raw PCM
        audio_array = np.frombuffer(audio_data, dtype=np.int16)
    
    print(f"🔊 Playing response audio ({len(audio_array)} samples @ {sample_rate}Hz)...")
    sd.play(audio_array, sample_rate)
    sd.wait()
    print("✅ Playback complete!")


async def test_conversation(gateway_url: str):
    """Run an interactive test session."""
    print("🦉 cAIru Interactive Test Client")
    print("=" * 50)
    print(f"Gateway: {gateway_url}")
    print("\nThis will:")
    print("  1. Record 3 seconds of audio from your microphone")
    print("  2. Send it to the cAIru pipeline")
    print("  3. Play back the response")
    print("\nPress Ctrl+C to exit.\n")
    
    while True:
        input("Press Enter to start recording (or Ctrl+C to quit)...")
        
        # Record audio
        audio_data = record_audio(duration_seconds=3.0)
        print(f"   Recorded {len(audio_data)} bytes")
        
        # Connect and send
        print(f"\n📡 Connecting to gateway...")
        try:
            # Increase max message size to 10MB for audio responses
            async with websockets.connect(gateway_url, max_size=10 * 1024 * 1024) as ws:
                print("   Connected!")
                
                # Send audio
                print("📤 Sending audio to pipeline...")
                start_time = time.time()
                await ws.send(audio_data)
                
                # Wait for response
                print("⏳ Waiting for response...")
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=15.0)
                    latency_ms = (time.time() - start_time) * 1000
                    
                    if isinstance(response, str):
                        data = json.loads(response)
                        print(f"\n📥 Response received in {latency_ms:.0f}ms")
                        print(f"   Type: {data.get('type', 'unknown')}")
                        
                        if 'text' in data:
                            print(f"   Text: {data['text']}")
                        
                        if 'audio' in data:
                            # Decode base64 audio and play
                            audio_bytes = base64.b64decode(data['audio'])
                            print(f"   Audio: {len(audio_bytes)} bytes")
                            play_audio(audio_bytes)
                        else:
                            print("   ⚠️ No audio in response")
                        
                        # Check latency target
                        if latency_ms < 800:
                            print(f"\n   🎉 Latency: {latency_ms:.0f}ms (target: <800ms) ✓")
                        else:
                            print(f"\n   ⚠️ Latency: {latency_ms:.0f}ms (target: <800ms) ✗")
                    
                    elif isinstance(response, bytes):
                        print(f"\n📥 Binary response: {len(response)} bytes in {latency_ms:.0f}ms")
                        play_audio(response)
                    
                except asyncio.TimeoutError:
                    print("   ❌ Timeout waiting for response (15s)")
                    print("   Possible causes:")
                    print("     - VAD didn't detect speech (try speaking louder)")
                    print("     - Pipeline service not running")
                    print("     - LLM taking too long")
                
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        print("\n" + "-" * 50)


async def test_with_file(gateway_url: str, audio_file: str):
    """Test with an audio file instead of microphone."""
    import wave
    
    print(f"🦉 Testing with audio file: {audio_file}")
    
    # Read audio file
    with wave.open(audio_file, 'rb') as wav:
        if wav.getframerate() != SAMPLE_RATE:
            print(f"⚠️ Warning: File is {wav.getframerate()}Hz, expected {SAMPLE_RATE}Hz")
        audio_data = wav.readframes(wav.getnframes())
    
    print(f"   Loaded {len(audio_data)} bytes")
    
    # Connect and send (increase max size for audio responses)
    async with websockets.connect(gateway_url, max_size=10 * 1024 * 1024) as ws:
        print("📤 Sending audio...")
        start_time = time.time()
        await ws.send(audio_data)
        
        print("⏳ Waiting for response...")
        response = await asyncio.wait_for(ws.recv(), timeout=15.0)
        latency_ms = (time.time() - start_time) * 1000
        
        if isinstance(response, str):
            data = json.loads(response)
            print(f"\n📥 Response in {latency_ms:.0f}ms:")
            print(f"   {data.get('text', 'No text')}")
            
            if 'audio' in data:
                audio_bytes = base64.b64decode(data['audio'])
                play_audio(audio_bytes)


def main():
    parser = argparse.ArgumentParser(description="Interactive test client for cAIru")
    parser.add_argument(
        "--gateway",
        default="ws://localhost:8080/ws",
        help="Gateway WebSocket URL (default: ws://localhost:8080/ws)",
    )
    parser.add_argument(
        "--file",
        help="Test with an audio file instead of microphone (16kHz WAV)",
    )
    args = parser.parse_args()
    
    try:
        if args.file:
            asyncio.run(test_with_file(args.gateway, args.file))
        else:
            asyncio.run(test_conversation(args.gateway))
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")


if __name__ == "__main__":
    main()

