# =============================================================================
# cAIru Base Station Makefile
# =============================================================================

.PHONY: help setup dev up down logs clean test lint build deploy

# Default target
help:
	@echo "cAIru Base Station - Development Commands"
	@echo ""
	@echo "Setup & Development:"
	@echo "  make setup      - Initial project setup"
	@echo "  make dev        - Start development environment with hot-reload"
	@echo "  make up         - Start all services in production mode"
	@echo "  make down       - Stop all services"
	@echo "  make logs       - Follow logs from all services"
	@echo ""
	@echo "Testing:"
	@echo "  make test       - Run all tests"
	@echo "  make lint       - Run linters"
	@echo ""
	@echo "Build & Deploy:"
	@echo "  make build      - Build all Docker images"
	@echo "  make deploy     - Deploy to N100 (requires N100_HOST env var)"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean      - Remove all containers and volumes"
	@echo "  make pull-models - Download required ML models"

# =============================================================================
# Setup
# =============================================================================

setup: .env
	@echo "Setting up cAIru development environment..."
	@pip install -e ./shared[dev]
	@echo "Pulling Docker images..."
	@docker compose pull redis ollama
	@echo "Setup complete! Run 'make dev' to start."

.env:
	@cp env.example .env
	@echo "Created .env from template"

# =============================================================================
# Development
# =============================================================================

dev:
	@echo "Starting development environment..."
	@docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

up:
	@docker compose up -d

down:
	@docker compose down

logs:
	@docker compose logs -f

logs-%:
	@docker compose logs -f $*

# =============================================================================
# Testing
# =============================================================================

test:
	@echo "Running tests..."
	@pytest tests/ -v

lint:
	@echo "Running linters..."
	@ruff check services/ shared/

# =============================================================================
# Build & Deploy
# =============================================================================

build:
	@echo "Building Docker images..."
	@docker compose build

deploy:
ifndef N100_HOST
	$(error N100_HOST is not set. Usage: N100_HOST=192.168.1.x make deploy)
endif
	@echo "Deploying to N100 at $(N100_HOST)..."
	@./scripts/deploy.sh $(N100_HOST)

# =============================================================================
# Model Management
# =============================================================================

pull-models:
	@echo "Pulling LLM model..."
	@docker compose up -d ollama
	@sleep 5
	@docker compose exec ollama ollama pull phi3:mini
	@echo "Models ready!"

# =============================================================================
# Utilities
# =============================================================================

clean:
	@echo "Cleaning up..."
	@docker compose down -v --remove-orphans
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@echo "Cleanup complete!"

redis-cli:
	@docker compose exec redis redis-cli
