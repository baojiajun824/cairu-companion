"""
Piper TTS synthesizer for text-to-speech.
"""

import asyncio
import io
from functools import partial

import numpy as np
import soundfile as sf

from cairu_common.logging import get_logger

logger = get_logger()


class PiperSynthesizer:
    """
    Text-to-speech synthesis using Piper.

    Piper is a fast, local neural TTS system that produces natural-sounding
    speech on CPU with low latency.
    """

    SAMPLE_RATE = 22050  # Piper default

    def __init__(self, voice: str = "en_US-lessac-medium", model_path: str = "/app/models"):
        """
        Initialize synthesizer.

        Args:
            voice: Piper voice identifier
            model_path: Path to model files
        """
        self.voice = voice
        self.model_path = model_path
        self._piper = None

    async def load_model(self):
        """Load the Piper voice model."""
        logger.info("loading_piper_model", voice=self.voice)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._load_model_sync)

        logger.info("piper_model_loaded", voice=self.voice)

    def _load_model_sync(self):
        """Synchronous model loading."""
        try:
            from piper import PiperVoice
            import os
            import urllib.request

            # Build model path
            onnx_file = os.path.join(self.model_path, f"{self.voice}.onnx")
            json_file = os.path.join(self.model_path, f"{self.voice}.onnx.json")

            # Check if model files exist, if not try to download
            if not os.path.exists(onnx_file) or not os.path.exists(json_file):
                logger.info("piper_model_not_found_downloading", voice=self.voice)
                try:
                    os.makedirs(self.model_path, exist_ok=True)
                    # Download from Piper's model repository
                    # Extract quality level from voice name (e.g., en_US-lessac-low -> low)
                    quality = self.voice.split("-")[-1]  # low, medium, or high
                    base_url = f"https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/{quality}/{self.voice}"
                    urllib.request.urlretrieve(f"{base_url}.onnx", onnx_file)
                    urllib.request.urlretrieve(f"{base_url}.onnx.json", json_file)
                    logger.info("piper_model_downloaded", voice=self.voice)
                except Exception as e:
                    logger.warning("piper_model_download_failed", error=str(e))
                    self._piper = None
                    return

            self._piper = PiperVoice.load(onnx_file)
            
        except ImportError:
            logger.warning("piper_not_installed_using_fallback")
            self._piper = None
        except Exception as e:
            logger.warning("piper_load_failed_using_fallback", error=str(e))
            self._piper = None

    async def synthesize(self, text: str) -> tuple[bytes, int]:
        """
        Synthesize speech from text.

        Args:
            text: Text to synthesize

        Returns:
            Tuple of (audio_bytes, duration_ms)
        """
        loop = asyncio.get_event_loop()
        audio_bytes, duration_ms = await loop.run_in_executor(
            None,
            partial(self._synthesize_sync, text),
        )

        return audio_bytes, duration_ms

    def _synthesize_sync(self, text: str) -> tuple[bytes, int]:
        """Synchronous speech synthesis."""
        if self._piper is None:
            # Fallback: generate silence for development
            return self._generate_silence(len(text) * 50)  # ~50ms per character

        # Synthesize with Piper (new API)
        audio_samples = []
        for audio_chunk in self._piper.synthesize(text):
            audio_samples.append(audio_chunk.audio_int16_array)

        if not audio_samples:
            return self._generate_silence(500)

        audio = np.concatenate(audio_samples)

        # Convert to WAV bytes
        buffer = io.BytesIO()
        sf.write(buffer, audio, self.SAMPLE_RATE, format="WAV", subtype="PCM_16")
        wav_bytes = buffer.getvalue()

        # Calculate duration
        duration_ms = int(len(audio) / self.SAMPLE_RATE * 1000)

        return wav_bytes, duration_ms

    def _generate_silence(self, duration_ms: int) -> tuple[bytes, int]:
        """Generate silent audio for development/fallback."""
        num_samples = int(self.SAMPLE_RATE * duration_ms / 1000)
        silence = np.zeros(num_samples, dtype=np.int16)

        buffer = io.BytesIO()
        sf.write(buffer, silence, self.SAMPLE_RATE, format="WAV", subtype="PCM_16")

        return buffer.getvalue(), duration_ms

