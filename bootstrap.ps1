# Bootstrap SAE System on a new Windows machine.
# Checks prerequisites, creates .env if missing, and starts the Docker stack.

$ErrorActionPreference = "Stop"

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

Write-Host "== SAE System bootstrap ==" -ForegroundColor Cyan

if (-not (Test-Command "docker")) {
    Write-Host "Docker was not found. Install Docker Desktop first:" -ForegroundColor Red
    Write-Host "  https://www.docker.com/products/docker-desktop/"
    exit 1
}

try {
    docker info *> $null
} catch {
    Write-Host "Docker is installed but not running. Start Docker Desktop and re-run this script." -ForegroundColor Red
    exit 1
}
Write-Host "[ok] Docker is running"

$envPath        = Join-Path $PSScriptRoot "sae_system\.env"
$envExamplePath = Join-Path $PSScriptRoot "sae_system\.env.example"
if (-not (Test-Path $envPath)) {
    Copy-Item $envExamplePath $envPath
    Write-Host "[ok] Created sae_system\.env from .env.example"
} else {
    Write-Host "[ok] sae_system\.env already exists — leaving it as-is"
}

# Read the actual configured model from .env rather than hardcoding a guess
# (config.py's OLLAMA_MODEL is the single source of truth — see Phase 10A's
# deployment doc for why this used to be a hardcoded "llama3.2" here).
$requiredModel = "llama3.2"
$envLine = Select-String -Path $envPath -Pattern "^OLLAMA_MODEL=" -ErrorAction SilentlyContinue
if ($envLine) {
    $requiredModel = ($envLine.Line -split "=", 2)[1].Trim()
}

if (-not (Test-Command "ollama")) {
    Write-Host "Ollama was not found. It runs on the host machine (not in Docker) so the AI stays local:" -ForegroundColor Yellow
    Write-Host "  1. Install from https://ollama.com/download"
    Write-Host "  2. Run:  ollama pull $requiredModel"
    Write-Host "Continuing setup — start Ollama before using the dashboard."
} else {
    Write-Host "[ok] Ollama is installed"
    $models = & ollama list 2>$null
    if ($models -notmatch [regex]::Escape($requiredModel)) {
        Write-Host "[!] $requiredModel isn't pulled yet — run:  ollama pull $requiredModel" -ForegroundColor Yellow
    } else {
        Write-Host "[ok] $requiredModel is pulled"
    }
}

Write-Host "Starting the Docker stack (Postgres, Redis, Neo4j, dashboard)..."
docker compose --env-file $envPath -f (Join-Path $PSScriptRoot "docker-compose.yml") up -d

Write-Host ""
Write-Host "== Done ==" -ForegroundColor Green
Write-Host "Dashboard:     http://localhost:8501"
Write-Host "Neo4j browser: http://localhost:7474  (neo4j / the NEO4J_PASSWORD from sae_system/.env)"
Write-Host ""
Write-Host "To move this student to another machine: copy the sae_system\data\ folder"
Write-Host "and sae_system\.env, then run this script there."
