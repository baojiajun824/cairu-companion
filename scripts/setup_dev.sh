#!/bin/bash
# =============================================================================
# cAIru Development Environment Setup
# =============================================================================

set -e

echo "🦉 Setting up cAIru development environment..."

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
if [[ "$PYTHON_VERSION" < "3.11" ]]; then
    echo "❌ Python 3.11+ is required. Found: $PYTHON_VERSION"
    exit 1
fi
echo "✅ Python $PYTHON_VERSION detected"

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker Desktop."
    exit 1
fi
echo "✅ Docker detected"

# Check Docker Compose
if ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose is not available. Please update Docker Desktop."
    exit 1
fi
echo "✅ Docker Compose detected"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install shared library
echo "📦 Installing shared library..."
pip install -e ./shared[dev]

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "📝 Creating .env from template..."
    cp env.example .env
    echo "⚠️  Please review .env and adjust settings as needed"
fi

# Create data directories
echo "📁 Creating data directories..."
mkdir -p data/orchestrator data/events data/dashboard

# Pull Docker images
echo "🐳 Pulling Docker images..."
docker compose pull redis ollama

# Start Redis and Ollama
echo "🚀 Starting infrastructure services..."
docker compose up -d redis ollama

# Wait for Ollama to be ready
echo "⏳ Waiting for Ollama to be ready..."
sleep 5

# Pull the default LLM model
echo "🤖 Pulling LLM model (this may take a while)..."
docker compose exec -T ollama ollama pull phi3:mini || echo "⚠️ Model pull failed - will retry on first use"

echo ""
echo "✅ Development environment setup complete!"
echo ""
echo "Next steps:"
echo "  1. Review and adjust .env settings"
echo "  2. Run 'make dev' to start all services"
echo "  3. Access the gateway at http://localhost:8080"
echo "  4. Access the dashboard API at http://localhost:8081"
echo ""
echo "Useful commands:"
echo "  make dev      - Start development environment"
echo "  make logs     - View service logs"
echo "  make test     - Run tests"
echo "  make help     - See all available commands"

