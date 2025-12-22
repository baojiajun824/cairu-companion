"""
Structured logging setup for cAIru services.

Provides JSON-formatted logs with correlation IDs for distributed tracing.
"""

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog
from structlog.types import Processor

# Context variable for request/trace correlation
correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
user_id: ContextVar[str | None] = ContextVar("user_id", default=None)


def add_correlation_id(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Add correlation ID to log entries if available."""
    if cid := correlation_id.get():
        event_dict["correlation_id"] = cid
    if uid := user_id.get():
        event_dict["user_id"] = uid
    return event_dict


def setup_logging(
    service_name: str,
    log_level: str = "INFO",
    json_format: bool = True,
) -> None:
    """
    Configure structured logging for a service.

    Args:
        service_name: Name of the service for log identification
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        json_format: Whether to output JSON (True) or console format (False)
    """
    # Shared processors for all log entries
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        add_correlation_id,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_format:
        # Production: JSON output
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        # Development: colored console output
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.UnicodeDecoder(),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Also configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper()),
    )

    # Log startup
    logger = get_logger()
    logger.info("logging_configured", service=service_name, level=log_level)


def get_logger() -> structlog.BoundLogger:
    """Get a configured structlog logger."""
    return structlog.get_logger()


def set_correlation_context(corr_id: str | None = None, usr_id: str | None = None):
    """Set correlation context for the current async context."""
    if corr_id:
        correlation_id.set(corr_id)
    if usr_id:
        user_id.set(usr_id)

