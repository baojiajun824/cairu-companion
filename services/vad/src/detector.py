"""
Silero VAD wrapper for voice activity detection with boundary detection.
"""

import asyncio
from functools import partial
from dataclasses import dataclass, field

import numpy as np
import torch

from cairu_common.logging import get_logger

logger = get_logger()


@dataclass
class VADState:
    """Tracks VAD state for a device/session."""
    is_speaking: bool = False
    audio_buffer: list = field(default_factory=list)
    speech_chunks: int = 0
    silence_chunks: int = 0
    
    # Thresholds for boundary detection
    # Client sends 100ms chunks, so adjust accordingly
    SPEECH_START_CHUNKS: int = 2   # 200ms of speech to start
    SILENCE_END_CHUNKS: int = 10   # 1 second of silence to end
    MIN_SPEECH_CHUNKS: int = 3     # 300ms minimum speech


class SileroVAD:
    """
    Voice Activity Detection using Silero VAD model.
    
    Now includes boundary detection - tracks when speech starts and ends.
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
        
        # Track state per session
        self._sessions: dict[str, VADState] = {}

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
            # Fallback: use simple energy-based detection
            return self._detect_energy(audio_bytes)

        # Run inference in executor to avoid blocking
        loop = asyncio.get_event_loop()
        probability = await loop.run_in_executor(
            None,
            partial(self._detect_sync, audio_bytes),
        )

        has_speech = probability >= self.threshold

        return has_speech, probability
    
    def _detect_energy(self, audio_bytes: bytes) -> tuple[bool, float]:
        """
        Simple energy-based VAD fallback.
        
        Works when Silero model isn't available.
        """
        # Convert to numpy
        audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
        
        # Calculate RMS energy
        rms = np.sqrt(np.mean(audio ** 2))
        
        # Normalize to 0-1 range (assuming 16-bit audio)
        # Typical speech RMS is ~2000-10000, silence is ~100-500
        normalized = min(rms / 5000.0, 1.0)
        
        # Threshold for speech detection
        has_speech = rms > 800  # Adjust based on your mic
        
        logger.debug("vad_energy", rms=round(rms, 0), has_speech=has_speech)
        
        return has_speech, normalized

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
    
    def get_session_state(self, session_id: str) -> VADState:
        """Get or create state for a session."""
        if session_id not in self._sessions:
            self._sessions[session_id] = VADState()
        return self._sessions[session_id]
    
    def reset_session(self, session_id: str):
        """Reset state for a session."""
        if session_id in self._sessions:
            del self._sessions[session_id]
    
    async def process_with_boundary(
        self, 
        session_id: str, 
        audio_bytes: bytes
    ) -> tuple[bool, bytes | None]:
        """
        Process audio chunk with boundary detection.
        
        Args:
            session_id: Session identifier for state tracking
            audio_bytes: Raw audio bytes (16kHz, 16-bit PCM)
            
        Returns:
            Tuple of (speech_ended, accumulated_audio_bytes or None)
            - speech_ended=True means we detected end of speech, audio contains full utterance
            - speech_ended=False means still listening, audio is None
        """
        state = self.get_session_state(session_id)
        
        # Detect speech in this chunk
        has_speech, probability = await self.detect(audio_bytes)
        
        # Debug logging
        logger.debug(
            "vad_chunk",
            session_id=session_id,
            has_speech=has_speech,
            prob=round(probability, 2),
            is_speaking=state.is_speaking,
            silence_chunks=state.silence_chunks,
        )
        
        if has_speech:
            state.speech_chunks += 1
            state.silence_chunks = 0
            state.audio_buffer.append(audio_bytes)
            
            # Start speaking
            if not state.is_speaking and state.speech_chunks >= state.SPEECH_START_CHUNKS:
                state.is_speaking = True
                logger.info("speech_started", session_id=session_id)
        else:
            state.silence_chunks += 1
            state.speech_chunks = 0
            
            # If we were speaking, still accumulate (captures trailing audio)
            if state.is_speaking:
                state.audio_buffer.append(audio_bytes)
            
            # End of speech detected
            if state.is_speaking and state.silence_chunks >= state.SILENCE_END_CHUNKS:
                # Check if we have enough speech
                total_chunks = len(state.audio_buffer)
                if total_chunks >= state.MIN_SPEECH_CHUNKS:
                    # Combine all audio
                    full_audio = b''.join(state.audio_buffer)
                    logger.info(
                        "speech_ended", 
                        session_id=session_id,
                        chunks=total_chunks,
                        duration_ms=total_chunks * 32,
                    )
                    
                    # Reset state for next utterance
                    self.reset_session(session_id)
                    
                    return True, full_audio
                else:
                    # Too short, discard
                    logger.debug("speech_too_short", session_id=session_id)
                    self.reset_session(session_id)
        
        return False, None

