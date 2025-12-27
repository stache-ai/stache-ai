#!/bin/bash
# RAGBrain setup script

set -e

echo "🧠 RAGBrain Setup"
echo "================="
echo

# Check for Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first:"
    echo "   https://docs.docker.com/get-docker/"
    exit 1
fi

# Check for Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first:"
    echo "   https://docs.docker.com/compose/install/"
    exit 1
fi

echo "✅ Docker and Docker Compose are installed"
echo

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚙️  Creating .env file..."
    cp .env.example .env
    echo "✅ .env file created"
    echo
    echo "📝 Please edit .env and add your API keys:"
    echo "   - ANTHROPIC_API_KEY (get from https://console.anthropic.com/)"
    echo "   - or OPENAI_API_KEY (get from https://platform.openai.com/)"
    echo
    read -p "Press Enter after you've added your API key to .env..."
else
    echo "✅ .env file exists"
fi

echo

# Check if API key is set
if ! grep -q "API_KEY=sk-" .env; then
    echo "⚠️  Warning: No API key found in .env file"
    echo "   Make sure to add ANTHROPIC_API_KEY or OPENAI_API_KEY"
    echo
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Create data directory
mkdir -p data/qdrant data/uploads
echo "✅ Created data directories"
echo

# Start services
echo "🚀 Starting RAGBrain services..."
docker-compose up -d

echo
echo "⏳ Waiting for services to start..."
sleep 5

# Check health
echo
echo "🏥 Checking health..."
if curl -s http://localhost:8000/health > /dev/null; then
    echo "✅ Backend is healthy!"
    curl -s http://localhost:8000/health | jq '.'
else
    echo "❌ Backend is not responding. Check logs:"
    echo "   docker-compose logs app"
    exit 1
fi

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎉 RAGBrain is running!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
echo "📡 API Endpoints:"
echo "   Health:  http://localhost:8000/health"
echo "   Capture: http://localhost:8000/api/capture"
echo "   Query:   http://localhost:8000/api/query"
echo "   Upload:  http://localhost:8000/api/upload"
echo
echo "🧪 Test it:"
echo "   curl http://localhost:8000/health"
echo
echo "📖 Next steps:"
echo "   - Capture a thought: curl -X POST http://localhost:8000/api/capture -H 'Content-Type: application/json' -d '{\"text\":\"Your thought here\"}'"
echo "   - Query: curl -X POST http://localhost:8000/api/query -H 'Content-Type: application/json' -d '{\"query\":\"Your question?\"}'"
echo "   - View logs: docker-compose logs -f app"
echo "   - Stop: docker-compose down"
echo
