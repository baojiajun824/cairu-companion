"""
Centralized configuration management for cAIru services.

Uses Pydantic Settings for environment variable loading and validation.
Simplified for Alpha: Single device, single user.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Base settings shared across all services."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General
    environment: Literal["development", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    service_name: str = Field(default="cairu-service", alias="OTEL_SERVICE_NAME")

    # Redis
    redis_url: RedisDsn = Field(default="redis://localhost:6379")

    # Feature flags
    enable_proactive_rules: bool = True

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


class GatewaySettings(Settings):
    """Settings specific to the Gateway service."""

    service_name: str = "gateway"
    gateway_host: str = "0.0.0.0"
    gateway_port: int = 8080


class ASRSettings(Settings):
    """Settings specific to the ASR service."""

    service_name: str = "asr"
    whisper_model: str = "tiny.en"  # Fastest model for low-latency
    whisper_device: str = "cpu"


class LLMSettings(Settings):
    """Settings specific to the LLM service."""

    service_name: str = "llm"
    llm_backend: Literal["ollama"] = "ollama"
    ollama_url: str = "http://localhost:11434"
    llm_model: str = "qwen2:0.5b"  # Fastest model for low-latency


class TTSSettings(Settings):
    """Settings specific to the TTS service."""

    service_name: str = "tts"
    piper_voice: str = "en_US-lessac-medium"
    piper_model_path: str = "/app/models"


class OrchestratorSettings(Settings):
    """Settings specific to the Orchestrator service."""

    service_name: str = "orchestrator"
    database_path: str = "/app/data/cairu.db"
    rules_config_path: str = "/app/config/rules/default_rules.yaml"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


@lru_cache
def get_gateway_settings() -> GatewaySettings:
    return GatewaySettings()


@lru_cache
def get_asr_settings() -> ASRSettings:
    return ASRSettings()


@lru_cache
def get_llm_settings() -> LLMSettings:
    return LLMSettings()


@lru_cache
def get_tts_settings() -> TTSSettings:
    return TTSSettings()


@lru_cache
def get_orchestrator_settings() -> OrchestratorSettings:
    return OrchestratorSettings()
