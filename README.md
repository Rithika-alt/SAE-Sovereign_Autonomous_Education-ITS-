# SAE System — Sovereign AI Education

A local-first, privacy-preserving adaptive learning platform powered by Ollama.

---

## Prerequisites

- **Python 3.10+** (3.11 recommended — what this project is developed and tested against)
- **[Ollama](https://ollama.com/download)** installed and running locally
- ~2.5GB free disk space (mostly the Ollama model)
- Windows, macOS, or Linux — no OS-specific code paths beyond the optional Docker stack

## Quick Start (local, no Docker)

```bash
cd sae_system
pip install -r requirements.txt
cp .env.example .env          # edit if needed
ollama pull llama3.2          # or whatever OLLAMA_MODEL is set to in .env
python scripts/check_environment.py   # verify everything is ready — see below
python scripts/start.py               # runs the check above, then starts the dashboard
```

Or skip the wrapper and run Streamlit directly once you've confirmed the
environment is ready:

```bash
streamlit run dashboard/app.py
```

### Environment check

`python scripts/check_environment.py` verifies Python version, all
required packages, Ollama installation/reachability, the configured model
(read from `config.py` — never hardcoded), local storage, and the optional
services (PostgreSQL/Redis/Neo4j — all optional, all have working local
fallbacks, so these only ever WARN, never FAIL). Exits non-zero if
something required is actually missing, with a suggested fix for each.

### Demo account

New install, want to log in immediately without registering by hand?

```bash
python scripts/seed_demo.py
```

Creates one account (`demo_student` / `SaeDemo123!`) via the app's real
registration path — safe to re-run, never touches a real student's data.

---

## Using Neo4j with Docker (recommended for full experience)

Neo4j gives you a live visual browser of every student's knowledge graph —
you can see which concepts are connected, which are mastered, and which are
still locked.

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running

### Start all services

From the project root (`SAE_SYSTEM/`):

```bash
docker-compose up -d
```

This starts PostgreSQL, Redis, Neo4j, and the Streamlit dashboard together.

### Access the Neo4j Browser

Open **http://localhost:7474** in your browser.

| Field    | Value       |
|----------|-------------|
| Username | `neo4j`     |
| Password | `saesystem` |

To see all concept nodes after generating a roadmap:

```cypher
MATCH (n) RETURN n
```

### Enable Neo4j in the app

By default the app uses the local NetworkX backend (no Docker needed).
To switch to Neo4j, edit `sae_system/.env`:

```env
USE_NEO4J=true
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=saesystem
```

Then restart the app.

### Stop containers

```bash
docker-compose down
```

### Data persistence

| Data | Location |
|------|----------|
| Graph data (Neo4j) | `./data/neo4j/` on your machine |
| Knowledge graphs (NetworkX) | `./data/knowledge_graphs/` |
| Roadmap cache | `./data/roadmaps/` |
| Lesson cache | `./data/lessons/` |
| Test cache | `./data/tests/` |

All data survives `docker-compose down` and container deletion.
Delete a folder to force regeneration of that data type.

---

## Running Tests

```bash
cd sae_system
pytest tests/
```

---

## Troubleshooting

Run `python scripts/check_environment.py` first — it diagnoses most of the
issues below with a specific suggested fix.

| Symptom | Likely cause | Fix |
|---|---|---|
| `python` not found / version error | Python not installed or too old | Install Python 3.10+ (3.11 recommended) |
| `pip install -r requirements.txt` fails | Missing system build tools, or a package needs a native library | Check the specific package's error; `opencv-python`/`sentence-transformers` occasionally need platform-specific wheels |
| "Ollama was not found" | Ollama not installed | Install from https://ollama.com/download |
| "Could not reach http://localhost:11434" | Ollama not running | Start the Ollama app, or run `ollama serve` |
| "Model not found" | Configured model not pulled | `ollama pull <model>` (the exact name `check_environment.py` reports, read from `config.py`) |
| Dashboard won't start / port in use | Something else is already on port 8501 | `streamlit run dashboard/app.py --server.port 8502` (or free port 8501) |
| Missing lesson/roadmap data | Normal on a fresh install | Generated automatically the first time you pick a domain (needs Ollama running); or run `scripts/seed_demo.py` for an immediate login |
| Postgres/Redis/Neo4j "not reachable" | These are all optional | Safe to ignore — the app falls back to local JSON files / in-memory cache / NetworkX automatically. Only relevant if you specifically want persistent Postgres or the Neo4j browser (see `docker-compose up -d`) |
| Slow graph operations, "Neo4j unavailable ... falling back" spam in logs | `USE_NEO4J=true` in `.env` but no Neo4j running | Set `USE_NEO4J=false` in `.env` (the default) unless you're actually running Neo4j |
| `SovereigntyError` on startup | `OLLAMA_BASE_URL` in `.env` points somewhere non-local | Set it back to `http://localhost:11434` — SAE will never call a hosted/external LLM provider, by design |
| Out of memory / very slow generation | Insufficient RAM for the Ollama model | See Hardware below; try a smaller model via `OLLAMA_MODEL` in `.env` and `ollama pull <model>` |

### Hardware

| | Minimum | Recommended |
|---|---|---|
| RAM | 8GB | 16GB (Ollama + browser + IDE comfortably) |
| Disk | ~3GB free (Python deps + one Ollama model) | ~5GB (headroom for multiple models/cached lessons) |
| CPU | Any 64-bit x86/ARM from the last ~5 years | Faster CPU or a GPU Ollama can use = faster generation |
| GPU | Not required | Optional — Ollama uses one automatically if present, significantly speeding up generation/grading |

Measured on the development machine: `llama3.2` is 2.0GB on disk;
`sae_system/data/` (this session's actual accumulated lessons, roadmaps,
knowledge graphs, and progress) is 314KB; the full `sae_system/` source
tree is 4.7MB.
