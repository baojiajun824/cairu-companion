#!/bin/bash
# =============================================================================
# cAIru Deployment Script for Intel N100
# =============================================================================

set -e

N100_HOST=${1:-$N100_HOST}

if [ -z "$N100_HOST" ]; then
    echo "Usage: ./deploy.sh <n100-host-or-ip>"
    echo "   or: N100_HOST=192.168.1.x ./deploy.sh"
    exit 1
fi

N100_USER=${N100_USER:-cairu}
N100_PATH=${N100_PATH:-/opt/cairu}

echo "🦉 Deploying cAIru to $N100_HOST..."

# Build Docker images
echo "🔨 Building Docker images..."
docker compose build

# Save images to tar files
echo "📦 Exporting Docker images..."
mkdir -p .deploy

SERVICES="gateway vad asr orchestrator llm tts events dashboard-api"
for service in $SERVICES; do
    echo "  Saving cairu-$service..."
    docker save calru-companion-ai-$service:latest | gzip > .deploy/$service.tar.gz
done

# Copy files to N100
echo "📤 Copying files to N100..."
ssh $N100_USER@$N100_HOST "mkdir -p $N100_PATH"

scp docker-compose.yml $N100_USER@$N100_HOST:$N100_PATH/
scp -r config $N100_USER@$N100_HOST:$N100_PATH/
scp env.example $N100_USER@$N100_HOST:$N100_PATH/

for service in $SERVICES; do
    echo "  Uploading $service..."
    scp .deploy/$service.tar.gz $N100_USER@$N100_HOST:$N100_PATH/
done

# Load images and start services on N100
echo "🚀 Starting services on N100..."
ssh $N100_USER@$N100_HOST << EOF
    cd $N100_PATH

    # Load Docker images
    for f in *.tar.gz; do
        echo "Loading \$f..."
        docker load < \$f
        rm \$f
    done

    # Create .env if doesn't exist
    if [ ! -f .env ]; then
        cp env.example .env
        echo "Created .env from template - please configure!"
    fi

    # Pull infrastructure images
    docker compose pull redis ollama

    # Start all services
    docker compose up -d

    # Pull LLM model
    echo "Pulling LLM model..."
    docker compose exec -T ollama ollama pull phi3:mini

    echo "Services started!"
    docker compose ps
EOF

# Cleanup
rm -rf .deploy

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Access points:"
echo "  Gateway:       http://$N100_HOST:8080"
echo "  Dashboard API: http://$N100_HOST:8081"
echo "  Prometheus:    http://$N100_HOST:9090 (if observability enabled)"
echo "  Grafana:       http://$N100_HOST:3000 (if observability enabled)"
echo ""
echo "View logs with: ssh $N100_USER@$N100_HOST 'cd $N100_PATH && docker compose logs -f'"

