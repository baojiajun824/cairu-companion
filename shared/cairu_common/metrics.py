"""
Prometheus metrics for cAIru services.

Provides pre-defined metrics for pipeline monitoring and performance tracking.
Simplified for Alpha.
"""

from prometheus_client import Counter, Gauge, Histogram, Info, generate_latest

# =============================================================================
# Service Info
# =============================================================================

SERVICE_INFO = Info("cairu_service", "Service information")

# =============================================================================
# Pipeline Latency Metrics
# =============================================================================

PIPELINE_LATENCY = Histogram(
    "cairu_pipeline_latency_ms",
    "End-to-end pipeline latency in milliseconds",
    ["device_id"],
    buckets=[100, 200, 300, 400, 500, 600, 700, 800, 1000, 1500, 2000, 5000],
)

VAD_LATENCY = Histogram(
    "cairu_vad_latency_ms",
    "Voice activity detection latency in milliseconds",
    buckets=[5, 10, 20, 50, 100],
)

ASR_LATENCY = Histogram(
    "cairu_asr_latency_ms",
    "Speech recognition latency in milliseconds",
    buckets=[50, 100, 200, 300, 500, 750, 1000, 2000],
)

LLM_LATENCY = Histogram(
    "cairu_llm_latency_ms",
    "LLM inference latency in milliseconds",
    ["model", "backend"],
    buckets=[100, 200, 300, 500, 750, 1000, 1500, 2000, 3000, 5000],
)

TTS_LATENCY = Histogram(
    "cairu_tts_latency_ms",
    "Text-to-speech latency in milliseconds",
    buckets=[20, 50, 100, 200, 300, 500],
)

# =============================================================================
# Throughput Metrics
# =============================================================================

REQUESTS_TOTAL = Counter(
    "cairu_requests_total",
    "Total number of requests processed",
    ["service", "status"],
)

MESSAGES_PROCESSED = Counter(
    "cairu_messages_processed_total",
    "Total messages processed by stream",
    ["stream", "consumer_group"],
)

AUDIO_SEGMENTS_RECEIVED = Counter(
    "cairu_audio_segments_received_total",
    "Total audio segments received from Companion device",
    ["device_id"],
)

# =============================================================================
# Session Metrics
# =============================================================================

ACTIVE_SESSIONS = Gauge(
    "cairu_active_sessions",
    "Number of currently active Companion sessions (0 or 1 for Alpha)",
)

# =============================================================================
# Health Metrics
# =============================================================================

COMPONENT_HEALTH = Gauge(
    "cairu_component_health",
    "Health status of components (1=healthy, 0=unhealthy)",
    ["component"],
)

REDIS_CONNECTION_STATUS = Gauge(
    "cairu_redis_connection_status",
    "Redis connection status (1=connected, 0=disconnected)",
)

# =============================================================================
# LLM Specific Metrics
# =============================================================================

LLM_TOKENS_USED = Counter(
    "cairu_llm_tokens_used_total",
    "Total tokens consumed by LLM",
    ["model", "type"],  # type: prompt, completion
)

LLM_FALLBACK_COUNT = Counter(
    "cairu_llm_fallback_total",
    "Number of times fallback responses were used",
    ["reason"],
)

# =============================================================================
# ASR Specific Metrics
# =============================================================================

ASR_CONFIDENCE = Histogram(
    "cairu_asr_confidence",
    "ASR transcription confidence scores",
    buckets=[0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.99],
)

ASR_AUDIO_DURATION = Histogram(
    "cairu_asr_audio_duration_ms",
    "Duration of audio segments processed by ASR",
    buckets=[500, 1000, 2000, 3000, 5000, 10000, 20000],
)

# =============================================================================
# Helper Functions
# =============================================================================


def set_service_info(name: str, version: str, environment: str) -> None:
    """Set service identification info."""
    SERVICE_INFO.info({
        "name": name,
        "version": version,
        "environment": environment,
    })


def get_metrics() -> bytes:
    """Generate Prometheus metrics output."""
    return generate_latest()


def record_pipeline_latency(device_id: str, latency_ms: float) -> None:
    """Record end-to-end pipeline latency."""
    PIPELINE_LATENCY.labels(device_id=device_id).observe(latency_ms)


def record_request(service: str, status: str = "success") -> None:
    """Record a processed request."""
    REQUESTS_TOTAL.labels(service=service, status=status).inc()


def set_component_health(component: str, healthy: bool) -> None:
    """Set health status of a component."""
    COMPONENT_HEALTH.labels(component=component).set(1 if healthy else 0)
