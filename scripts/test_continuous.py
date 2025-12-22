#!/usr/bin/env python3
"""
Continuous listening test client for cAIru Base Station.

Always listens and uses VAD to detect speech start/end automatically.

Usage:
    python scripts/test_continuous.py

Requirements:
    pip install websockets sounddevice numpy
"""

import argparse
import asyncio
import base64
import json
import sys
import threading
import time
from collections import deque

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


# Audio settings
SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = np.int16
CHUNK_DURATION_MS = 100  # Process audio in 100ms chunks
CHUNK_SIZE = int(SAMPLE_RATE * CHUNK_DURATION_MS / 1000)

# VAD settings (simple energy-based)
ENERGY_THRESHOLD = 500  # Adjust based on your microphone
SPEECH_START_CHUNKS = 3  # Need 3 consecutive chunks above threshold to start
SILENCE_END_CHUNKS = 10  # Need 10 consecutive chunks below threshold to end (~1 second)
MIN_SPEECH_CHUNKS = 5  # Minimum speech length to send (~0.5 seconds)
MAX_SPEECH_DURATION = 30  # Maximum recording duration in seconds


class SimpleVAD:
    """Simple energy-based Voice Activity Detection."""
    
    def __init__(
        self,
        energy_threshold: float = ENERGY_THRESHOLD,
        speech_start_chunks: int = SPEECH_START_CHUNKS,
        silence_end_chunks: int = SILENCE_END_CHUNKS,
    ):
        self.energy_threshold = energy_threshold
        self.speech_start_chunks = speech_start_chunks
        self.silence_end_chunks = silence_end_chunks
        
        self.is_speaking = False
        self.consecutive_speech = 0
        self.consecutive_silence = 0
        
    def reset(self):
        """Reset VAD state."""
        self.is_speaking = False
        self.consecutive_speech = 0
        self.consecutive_silence = 0
        
    def process(self, audio_chunk: np.ndarray) -> tuple[bool, bool]:
        """
        Process an audio chunk and detect speech.
        
        Returns:
            Tuple of (is_speaking, speech_ended)
        """
        # Calculate RMS energy
        energy = np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2))
        
        speech_detected = energy > self.energy_threshold
        speech_ended = False
        
        if speech_detected:
            self.consecutive_speech += 1
            self.consecutive_silence = 0
            
            if not self.is_speaking and self.consecutive_speech >= self.speech_start_chunks:
                self.is_speaking = True
                
        else:
            self.consecutive_silence += 1
            self.consecutive_speech = 0
            
            if self.is_speaking and self.consecutive_silence >= self.silence_end_chunks:
                speech_ended = True
                self.is_speaking = False
                
        return self.is_speaking, speech_ended


class InterruptiblePlayer:
    """Audio player that can be interrupted."""
    
    def __init__(self):
        self.is_playing = False
        self._interrupt_event = threading.Event()
    
    @property
    def _interrupted(self):
        return self._interrupt_event.is_set()
    
    @_interrupted.setter
    def _interrupted(self, value):
        if value:
            self._interrupt_event.set()
        else:
            self._interrupt_event.clear()
    
    def stop(self):
        """Stop current playback immediately."""
        self._interrupt_event.set()
        try:
            sd.stop()
        except Exception:
            pass
    
    async def play_async(self, audio_data: bytes, sample_rate: int = 22050):
        """Play audio, can be interrupted by calling stop()."""
        self._interrupt_event.clear()
        self.is_playing = True
        
        try:
            # Parse audio
            if audio_data[:4] == b'RIFF':
                import wave
                import io
                wav_io = io.BytesIO(audio_data)
                with wave.open(wav_io, 'rb') as wav:
                    sr = wav.getframerate()
                    n_channels = wav.getnchannels()
                    frames = wav.readframes(wav.getnframes())
                    audio_array = np.frombuffer(frames, dtype=np.int16)
                    if n_channels == 2:
                        audio_array = audio_array.reshape(-1, 2)
            else:
                sr = sample_rate
                audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            # Calculate duration for timeout
            duration_sec = len(audio_array) / sr
            
            # Start playback (non-blocking)
            sd.play(audio_array, sr)
            
            # Wait with periodic interrupt check
            start = time.time()
            while (time.time() - start) < (duration_sec + 0.2):
                # Use is_set() for non-blocking check
                if self._interrupt_event.is_set():
                    print("   [Interrupt detected, stopping...]")
                    sd.stop()
                    return False
                await asyncio.sleep(0.01)  # Check every 10ms
            
            return True
        finally:
            self.is_playing = False
            try:
                sd.stop()
            except Exception:
                pass


async def continuous_listen(gateway_url: str, energy_threshold: float):
    """Continuously listen and send speech to the gateway."""
    print("🦉 cAIru Continuous Listening Client")
    print("=" * 50)
    print(f"Gateway: {gateway_url}")
    print(f"Energy threshold: {energy_threshold}")
    print("\n🎤 Listening... (speak to interrupt, Ctrl+C to quit)\n")
    
    vad = SimpleVAD(energy_threshold=energy_threshold)
    audio_buffer = []
    waiting_for_response = False
    player = InterruptiblePlayer()
    
    # Audio callback for continuous recording
    audio_queue = asyncio.Queue()
    
    def audio_callback(indata, frames, time_info, status):
        if status:
            print(f"Audio status: {status}")
        # Quick energy check for interrupt detection during playback
        if player.is_playing and not player._interrupt_event.is_set():
            chunk = indata.flatten()
            energy = np.sqrt(np.mean(chunk.astype(np.float32) ** 2))
            if energy > energy_threshold * 1.2:
                # Set event so play_async loop will see it
                player._interrupt_event.set()
                print("   [Voice detected during playback!]")
        audio_queue.put_nowait(indata.copy())
    
    # Start audio stream
    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
        blocksize=CHUNK_SIZE,
        callback=audio_callback,
    )
    
    try:
        # Disable ping timeout to avoid disconnection during audio playback
        async with websockets.connect(
            gateway_url,
            max_size=10 * 1024 * 1024,
            ping_interval=None,  # Disable ping/pong
        ) as ws:
            print("📡 Connected to gateway\n")
            
            with stream:
                while True:
                    # Get audio chunk from queue
                    try:
                        chunk = await asyncio.wait_for(
                            audio_queue.get(),
                            timeout=0.5
                        )
                    except asyncio.TimeoutError:
                        continue
                    
                    chunk_flat = chunk.flatten()
                    
                    # Skip processing while audio is playing (handled via interrupt flag)
                    if player.is_playing:
                        continue
                    
                    # Skip processing while waiting for response
                    if waiting_for_response:
                        continue
                    
                    # Process with VAD
                    is_speaking, speech_ended = vad.process(chunk_flat)
                    
                    if is_speaking or audio_buffer:
                        # Accumulate audio while speaking
                        audio_buffer.append(chunk_flat)
                        
                        # Show speaking indicator
                        if is_speaking and len(audio_buffer) == 1:
                            print("🗣️  Speaking detected...", end="", flush=True)
                        
                        # Check for max duration
                        duration = len(audio_buffer) * CHUNK_DURATION_MS / 1000
                        if duration > MAX_SPEECH_DURATION:
                            speech_ended = True
                    
                    if speech_ended and len(audio_buffer) >= MIN_SPEECH_CHUNKS:
                        print(f" ({len(audio_buffer) * CHUNK_DURATION_MS / 1000:.1f}s)")
                        
                        # Combine audio chunks
                        full_audio = np.concatenate(audio_buffer)
                        audio_bytes = full_audio.tobytes()
                        
                        print("📤 Sending to pipeline...")
                        start_time = time.time()
                        
                        # Send audio
                        await ws.send(audio_bytes)
                        
                        # Wait for response
                        waiting_for_response = True
                        print("⏳ Waiting for response...")
                        
                        try:
                            response = await asyncio.wait_for(ws.recv(), timeout=30.0)
                            latency_ms = (time.time() - start_time) * 1000
                            
                            if isinstance(response, str):
                                data = json.loads(response)
                                print(f"\n📥 Response ({latency_ms:.0f}ms):")
                                print(f"   \"{data.get('text', '')}\"")
                                
                                if 'audio' in data:
                                    audio_bytes = base64.b64decode(data['audio'])
                                    print(f"🔊 Playing audio ({len(audio_bytes)} bytes)... [speak to interrupt]")
                                    completed = await player.play_async(audio_bytes)
                                    if completed:
                                        print("✅ Done")
                                    else:
                                        # Interrupted! Start fresh for new speech
                                        print("🛑 Interrupted - listening for new speech...")
                                        # Drain old audio from queue
                                        while not audio_queue.empty():
                                            try:
                                                audio_queue.get_nowait()
                                            except:
                                                break
                                else:
                                    print("   ⚠️ No audio in response")
                            
                        except asyncio.TimeoutError:
                            print("   ❌ Timeout waiting for response")
                        
                        # Reset for next utterance
                        audio_buffer = []
                        vad.reset()
                        waiting_for_response = False
                        print("\n🎤 Listening...\n")
                    
                    elif speech_ended:
                        # Too short, discard
                        audio_buffer = []
                        vad.reset()
                        
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
    except Exception as e:
        print(f"\n❌ Error: {e}")


def calibrate_threshold():
    """Calibrate the energy threshold based on ambient noise."""
    print("🔧 Calibrating microphone...")
    print("   Please stay quiet for 2 seconds...")
    
    # Record ambient noise
    duration = 2.0
    recording = sd.rec(
        int(duration * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
    )
    sd.wait()
    
    # Calculate energy
    energy = np.sqrt(np.mean(recording.astype(np.float32) ** 2))
    
    # Set threshold at 3x ambient noise
    threshold = energy * 3
    
    print(f"   Ambient energy: {energy:.0f}")
    print(f"   Recommended threshold: {threshold:.0f}")
    
    return max(threshold, 200)  # Minimum threshold of 200


def main():
    parser = argparse.ArgumentParser(description="Continuous listening test client")
    parser.add_argument(
        "--gateway",
        default="ws://localhost:8080/ws",
        help="Gateway WebSocket URL",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Energy threshold for VAD (auto-calibrate if not set)",
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Run calibration and exit",
    )
    args = parser.parse_args()
    
    if args.calibrate:
        calibrate_threshold()
        return
    
    # Auto-calibrate if no threshold provided
    if args.threshold is None:
        threshold = calibrate_threshold()
    else:
        threshold = args.threshold
    
    print()
    
    try:
        asyncio.run(continuous_listen(args.gateway, threshold))
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")


if __name__ == "__main__":
    main()

