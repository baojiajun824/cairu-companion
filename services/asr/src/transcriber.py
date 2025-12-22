"""
Faster-Whisper transcriber for speech recognition.
"""

import asyncio
from functools import partial
import io

import numpy as np
from faster_whisper import WhisperModel

from cairu_common.logging import get_logger

logger = get_logger()


class WhisperTranscriber:
    """
    Speech-to-text transcription using Faster-Whisper.

    Faster-Whisper is a reimplementation of OpenAI's Whisper using CTranslate2,
    providing 4x faster inference on CPU with lower memory usage.
    """

    SAMPLE_RATE = 16000

    def __init__(
        self,
        model_size: str = "small.en",
        device: str = "cpu",
        compute_type: str = "int8",
    ):
        """
        Initialize transcriber.

        Args:
            model_size: Whisper model size (tiny.en, base.en, small.en, medium.en)
            device: Device to run on ("cpu" or "cuda")
            compute_type: Computation type for quantization
        """
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.model: WhisperModel | None = None

    async def load_model(self):
        """Load the Whisper model."""
        logger.info(
            "loading_whisper_model",
            model=self.model_size,
            device=self.device,
        )

        loop = asyncio.get_event_loop()
        self.model = await loop.run_in_executor(
            None,
            self._load_model_sync,
        )

        logger.info("whisper_model_loaded", model=self.model_size)

    def _load_model_sync(self) -> WhisperModel:
        """Synchronous model loading."""
        return WhisperModel(
            self.model_size,
            device=self.device,
            compute_type=self.compute_type,
        )

    async def transcribe(self, audio_bytes: bytes) -> tuple[str, float]:
        """
        Transcribe audio to text.

        Args:
            audio_bytes: Raw audio bytes (16kHz, 16-bit PCM)

        Returns:
            Tuple of (transcribed_text, average_confidence)
        """
        if self.model is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        loop = asyncio.get_event_loop()
        text, confidence = await loop.run_in_executor(
            None,
            partial(self._transcribe_sync, audio_bytes),
        )

        return text, confidence

    def _transcribe_sync(self, audio_bytes: bytes) -> tuple[str, float]:
        """Synchronous transcription."""
        # Convert bytes to numpy array (16-bit PCM)
        audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)

        # Normalize to float32 [-1, 1]
        audio_float = audio_int16.astype(np.float32) / 32768.0

        # Transcribe
        segments, info = self.model.transcribe(
            audio_float,
            beam_size=5,
            language="en",
            vad_filter=True,  # Additional VAD filtering
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            ),
        )

        # Collect segments and calculate average confidence
        text_parts = []
        confidences = []

        for segment in segments:
            text_parts.append(segment.text.strip())
            # Avg log probability is negative; convert to confidence
            confidences.append(np.exp(segment.avg_logprob))

        full_text = " ".join(text_parts)
        avg_confidence = np.mean(confidences) if confidences else 0.0

        return full_text, float(avg_confidence)

