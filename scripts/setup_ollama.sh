#!/bin/bash
# scripts/setup_ollama.sh — Download and configure Ollama models for BrokerBot
# Run this once after installing Ollama (https://ollama.ai)

set -e

echo "🤖 BrokerBot — Ollama Model Setup"
echo "=================================="

# Check Ollama is installed
if ! command -v ollama &> /dev/null; then
    echo "❌ Ollama not found. Install from https://ollama.ai"
    exit 1
fi

# Check Ollama is running
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "⚠️  Ollama not running. Starting..."
    ollama serve &
    sleep 3
fi

echo ""
echo "📥 Downloading conversation model (Qwen3 8B Q4_K_M ~6GB)..."
ollama pull qwen3:8b-q4_K_M || ollama pull qwen3:8b

echo ""
echo "📥 Downloading vision model (Qwen2.5-VL 7B Q4_K_M ~6GB)..."
ollama pull qwen2.5-vl:7b-q4_K_M || ollama pull qwen2.5-vl:7b

echo ""
echo "✅ Models downloaded. Verifying..."
ollama list

echo ""
echo "🏥 Quick health check..."
curl -s http://localhost:11434/api/tags | python3 -c "
import json, sys
data = json.load(sys.stdin)
models = [m['name'] for m in data.get('models', [])]
print(f'  Models available: {len(models)}')
for m in models:
    print(f'  ✓ {m}')
"

echo ""
echo "✅ Ollama setup complete!"
echo ""
echo "Next steps:"
echo "  1. cp .env.example .env"
echo "  2. Edit .env with your Telegram bot tokens"
echo "  3. docker compose up -d  (PostgreSQL + Redis)"
echo "  4. uv sync  (install Python dependencies)"
echo "  5. alembic upgrade head  (create DB tables)"
echo "  6. python -m src.main  (start BrokerBot)"
