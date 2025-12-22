# =============================================================================
# cAIru LLM Service Dockerfile
# =============================================================================

FROM python:3.11-slim AS production

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash cairu
USER cairu

COPY --chown=cairu:cairu services/llm/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=cairu:cairu shared/ /app/shared/
RUN pip install --user -e /app/shared

COPY --chown=cairu:cairu services/llm/src/ /app/src/

CMD ["python", "-m", "src.main"]
