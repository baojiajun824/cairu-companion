#!/usr/bin/env python3
"""
End-to-end pipeline test for cAIru Base Station.

Simulates a Companion device connecting and sending audio,
then verifies the response comes back through the pipeline.
"""

import asyncio
import base64
import json
import time
import wave
import io

import websockets


GATEWAY_URL = "ws://localhost:8080/ws"
TEST_AUDIO_DURATION_MS = 2000  # 2 seconds of test audio


def generate_test_audio(duration_ms: int = 2000) -> bytes:
    """Generate test audio with a tone (16kHz, 16-bit mono PCM)."""
    import struct
    import math

    sample_rate = 16000
    num_samples = int(sample_rate * duration_ms / 1000)
    frequency = 440  # A4 note

    # Generate a sine wave tone (simulates voice-like audio)
    samples = []
    for i in range(num_samples):
        t = i / sample_rate
        # Mix multiple frequencies to simulate speech-like audio
        value = (
            0.5 * math.sin(2 * math.pi * frequency * t) +
            0.3 * math.sin(2 * math.pi * frequency * 2 * t) +
            0.2 * math.sin(2 * math.pi * frequency * 3 * t)
        )
        samples.append(int(value * 16000))  # Scale to 16-bit range

    # Pack as 16-bit PCM
    audio_bytes = struct.pack(f"<{len(samples)}h", *samples)

    return audio_bytes


async def test_full_pipeline():
    """Test the complete audio → response pipeline."""
    print("🦉 cAIru Pipeline Test")
    print("=" * 50)

    # Generate test audio
    print("\n1. Generating test audio...")
    audio_data = generate_test_audio(TEST_AUDIO_DURATION_MS)
    print(f"   Generated {len(audio_data)} bytes ({TEST_AUDIO_DURATION_MS}ms)")

    # Connect to gateway
    print(f"\n2. Connecting to gateway: {GATEWAY_URL}")
    try:
        async with websockets.connect(GATEWAY_URL) as ws:
            print("   ✅ Connected!")

            # Send audio
            print("\n3. Sending audio to pipeline...")
            start_time = time.time()
            await ws.send(audio_data)
            print(f"   Sent {len(audio_data)} bytes")

            # Wait for response
            print("\n4. Waiting for response...")
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=10.0)
                end_time = time.time()
                latency_ms = (end_time - start_time) * 1000

                # Parse response
                if isinstance(response, str):
                    data = json.loads(response)
                    print(f"   ✅ Response received in {latency_ms:.0f}ms")
                    print(f"   Type: {data.get('type')}")
                    print(f"   Text: {data.get('text', 'N/A')[:100]}")
                    print(f"   Has audio: {'audio' in data}")

                    if latency_ms < 800:
                        print(f"\n   🎉 Latency target MET! ({latency_ms:.0f}ms < 800ms)")
                    else:
                        print(f"\n   ⚠️ Latency target MISSED ({latency_ms:.0f}ms > 800ms)")

                else:
                    print(f"   ✅ Binary response received: {len(response)} bytes")

            except asyncio.TimeoutError:
                print("   ❌ Timeout waiting for response (10s)")
                return False

    except Exception as e:
        print(f"   ❌ Connection failed: {e}")
        return False

    print("\n" + "=" * 50)
    print("Pipeline test complete!")
    return True


async def test_gateway_health():
    """Test gateway health endpoint."""
    import aiohttp

    print("\nChecking service health...")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get("http://localhost:8080/health", timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"  ✅ Gateway: {data.get('status', 'ok')}")
                    print(f"     Redis: {data.get('redis', 'unknown')}")
                else:
                    print(f"  ⚠️ Gateway: HTTP {resp.status}")
        except Exception as e:
            print(f"  ❌ Gateway: {e}")


async def main():
    """Run all tests."""
    try:
        # First check health
        await test_gateway_health()

        # Then run pipeline test
        print("\n")
        success = await test_full_pipeline()

        exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\nTest interrupted")
        exit(1)


if __name__ == "__main__":
    asyncio.run(main())

