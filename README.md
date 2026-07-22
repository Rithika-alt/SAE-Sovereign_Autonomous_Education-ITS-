# SAE System — Sovereign AI Education

A local-first, privacy-preserving adaptive learning platform powered by Ollama.

---

## Quick Start (local, no Docker)

```bash
cd sae_system
pip install -r requirements.txt
cp .env.example .env          # edit if needed
streamlit run dashboard/app.py
```

Ollama must be running locally with the model pulled:

```bash
ollama pull llama3.2
```

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
