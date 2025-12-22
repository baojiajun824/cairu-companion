"""
Silero VAD wrapper for voice activity detection.
"""

import asyncio
from functools import partial

import numpy as np
import torch

from cairu_common.logging import get_logger

logger = get_logger()


class SileroVAD:
    """
    Voice Activity Detection using Silero VAD model.

    Silero VAD is a small, fast model that runs efficiently on CPU.
    See: https://github.com/snakers4/silero-vad
    """

    # Audio parameters expected by Silero
    SAMPLE_RATE = 16000
    CHUNK_SIZE = 512  # 32ms at 16kHz

    def __init__(self, threshold: float = 0.5):
        """
        Initialize VAD.

        Args:
            threshold: Speech probability threshold (0.0-1.0)
        """
        self.threshold = threshold
        self.model = None
        self._utils = None

    async def load_model(self):
        """Load the Silero VAD model."""
        logger.info("loading_silero_vad")

        # Run in executor to avoid blocking
        loop = asyncio.get_event_loop()
        self.model, self._utils = await loop.run_in_executor(
            None,
            self._load_model_sync,
        )

        logger.info("silero_vad_loaded")

    def _load_model_sync(self):
        """Synchronous model loading."""
        try:
            model, utils = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
                onnx=True,  # Use ONNX for better compatibility
            )
            return model, utils
        except Exception as e:
            logger.warning("silero_vad_load_failed_using_fallback", error=str(e))
            return None, None

    async def detect(self, audio_bytes: bytes) -> tuple[bool, float]:
        """
        Detect voice activity in audio.

        Args:
            audio_bytes: Raw audio bytes (16kHz, 16-bit PCM)

        Returns:
            Tuple of (has_speech, probability)
        """
        if self.model is None:
            # Fallback: pass everything through (for development)
            logger.debug("vad_fallback_passthrough")
            return True, 1.0

        # Run inference in executor to avoid blocking
        loop = asyncio.get_event_loop()
        probability = await loop.run_in_executor(
            None,
            partial(self._detect_sync, audio_bytes),
        )

        has_speech = probability >= self.threshold

        return has_speech, probability

    def _detect_sync(self, audio_bytes: bytes) -> float:
        """Synchronous VAD inference."""
        # Convert bytes to numpy array (16-bit PCM)
        audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)

        # Normalize to float32 [-1, 1]
        audio_float = audio_int16.astype(np.float32) / 32768.0

        # Convert to tensor
        audio_tensor = torch.from_numpy(audio_float)

        # Get speech probability
        with torch.no_grad():
            speech_prob = self.model(audio_tensor, self.SAMPLE_RATE).item()

        return speech_prob

    def reset_states(self):
        """Reset model states (call between different audio streams)."""
        if self.model is not None:
            self.model.reset_states()

