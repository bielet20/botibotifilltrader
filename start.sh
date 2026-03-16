#!/bin/bash
# Start the Trading Bot API Server
# Run this script from the project root directory:
#   bash start.sh

cd "$(dirname "$0")"

# Use local venv if it exists, otherwise try system uvicorn
if [ -f ".venv/bin/uvicorn" ]; then
    echo "✅ Starting with local .venv..."
    .venv/bin/uvicorn apps.api.main:app --reload --port 8000
elif command -v uvicorn &> /dev/null; then
    echo "✅ Starting with system uvicorn..."
    uvicorn apps.api.main:app --reload --port 8000
else
    echo "❌ uvicorn not found. Run: .venv/bin/pip install uvicorn"
    exit 1
fi
