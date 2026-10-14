#!/usr/bin/env bash
# Bootstrap SAE System on a new Mac/Linux machine.
# Checks prerequisites, creates .env if missing, and starts the Docker stack.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "== SAE System bootstrap =="

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker was not found. Install Docker first: https://www.docker.com/products/docker-desktop/"
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "Docker is installed but not running. Start it and re-run this script."
    exit 1
fi
echo "[ok] Docker is running"

ENV_PATH="$SCRIPT_DIR/sae_system/.env"
ENV_EXAMPLE_PATH="$SCRIPT_DIR/sae_system/.env.example"
if [ ! -f "$ENV_PATH" ]; then
    cp "$ENV_EXAMPLE_PATH" "$ENV_PATH"
    echo "[ok] Created sae_system/.env from .env.example"
else
    echo "[ok] sae_system/.env already exists — leaving it as-is"
fi

# Read the actual configured model from .env rather than hardcoding a guess
# (config.py's OLLAMA_MODEL is the single source of truth).
REQUIRED_MODEL="llama3.2"
if grep -q "^OLLAMA_MODEL=" "$ENV_PATH" 2>/dev/null; then
    REQUIRED_MODEL="$(grep "^OLLAMA_MODEL=" "$ENV_PATH" | head -1 | cut -d= -f2- | tr -d '[:space:]')"
fi

if ! command -v ollama >/dev/null 2>&1; then
    echo "Ollama was not found. It runs on the host machine (not in Docker) so the AI stays local:"
    echo "  1. Install from https://ollama.com/download"
    echo "  2. Run:  ollama pull $REQUIRED_MODEL"
    echo "Continuing setup — start Ollama before using the dashboard."
else
    echo "[ok] Ollama is installed"
    if ! ollama list 2>/dev/null | grep -q "$REQUIRED_MODEL"; then
        echo "[!] $REQUIRED_MODEL isn't pulled yet — run:  ollama pull $REQUIRED_MODEL"
    else
        echo "[ok] $REQUIRED_MODEL is pulled"
    fi
fi

echo "Starting the Docker stack (Postgres, Redis, Neo4j, dashboard)..."
docker compose --env-file "$ENV_PATH" -f "$SCRIPT_DIR/docker-compose.yml" up -d

echo ""
echo "== Done =="
echo "Dashboard:     http://localhost:8501"
echo "Neo4j browser: http://localhost:7474  (neo4j / the NEO4J_PASSWORD from sae_system/.env)"
echo ""
echo "To move this student to another machine: copy the sae_system/data/ folder"
echo "and sae_system/.env, then run this script there."
