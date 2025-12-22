# =============================================================================
# cAIru Gateway Service Dockerfile
# =============================================================================

# Production stage
FROM python:3.11-slim AS production

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash cairu
USER cairu

# Install Python dependencies
COPY --chown=cairu:cairu services/gateway/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Install shared library
COPY --chown=cairu:cairu shared/ /app/shared/
RUN pip install --user -e /app/shared

# Copy source code
COPY --chown=cairu:cairu services/gateway/src/ /app/src/

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run in production mode
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
