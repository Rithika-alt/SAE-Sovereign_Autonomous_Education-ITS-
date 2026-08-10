# 🎓 Sovereign Autonomous Education (SAE)
### A Local-First, Multi-Agent Intelligent Tutoring System

[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agentic_Orchestration-orange)](https://github.com/langchain-ai/langgraph)
[![Ollama](https://img.shields.io/badge/Ollama-Local_LLM-green)](https://ollama.ai)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector_DB-purple)](https://www.trychroma.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-UI-red)](https://streamlit.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Stars](https://img.shields.io/github/stars/Rithika-alt/SAE-Sovereign_Autonomous_Education-ITS-?style=social)](https://github.com/Rithika-alt/SAE-Sovereign_Autonomous_Education-ITS-)

> **Zero cloud dependency. Full data sovereignty. AI tutoring that actually understands you.**

SAE is a fully local, privacy-preserving Multi-Agent Intelligent Tutoring System (ITS) that personalises learning paths, teaches interactively, grades subjective answers on *conceptual understanding* (not keyword matching), and issues cryptographically verifiable Proof-of-Learning credentials — all without sending a single byte of student data to an external server.

---

## ✨ Why SAE?

| Problem with existing AI tutors | How SAE solves it |
|---|---|
| Send all student data to cloud APIs (OpenAI, Google) | 100% local inference via Ollama — zero data leaves your machine |
| Grade answers by keyword matching — penalises paraphrase-correct responses | Cosine similarity on Sentence Transformer embeddings evaluates *meaning*, not words |
| No long-term memory of student progress | Dynamic Knowledge Graph (Neo4j) tracks concept mastery across sessions |
| No verifiable proof of what was learned | SHA-256 cryptographic mastery certificates, independently auditable |
| Generic one-size-fits-all curriculum | 4 autonomous agents build a personalised path per student, per domain |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  LAYER 1: MULTIMODAL INGESTION           │
│         Text Parser │ Whisper Audio │ Vision │ Biometric │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│            LAYER 2: AGENTIC ORCHESTRATION (LangGraph)    │
│   ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│   │ Tutor Agent │  │Searcher Agent│  │ Auditor Agent │  │
│   │(Curriculum) │  │ (RAG/Web)    │  │ (Grading)     │  │
│   └─────────────┘  └──────────────┘  └───────────────┘  │
│              ◄── Self-Correction Audit Loop ──►          │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│           LAYER 3: SOVEREIGN MEMORY ARCHITECTURE         │
│        ChromaDB (Vector DB) │ Neo4j (Knowledge Graph)    │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│              LAYER 4: TRUST & VERIFICATION               │
│     Anti-Malpractice Audit │ SHA-256 Proof-of-Learning   │
└─────────────────────────────────────────────────────────┘
```

---

## 🤖 The Four Agents

| Agent | Role |
|---|---|
| **🗺️ Roadmap Agent** | Queries the knowledge graph and builds a personalised multi-week learning path based on the student's current mastery frontier |
| **📚 Tutor Agent** | Generates structured lesson content via local Ollama LLM inference — Introduction, Core Theory, Worked Example, Misconceptions, Applications, Takeaways |
| **🔍 Searcher Agent** | Triggered when a concept is absent from ChromaDB — performs constrained web retrieval, embeds and writes back to the local vector store |
| **✅ Auditor Agent** | Evaluates student answers using the composite semantic score (cosine similarity × 0.7 + Socratic probe × 0.3) with anti-malpractice verification |

---

## 🧠 Semantic Grading — How It Works

Traditional ITS grade by keyword matching. SAE doesn't.

```
Student Answer → Sentence Transformer (all-MiniLM-L6-v2) → Embedding Vector
Reference Answer → Sentence Transformer → Embedding Vector
                                    ↓
                    Cosine Similarity (S_semantic) × 0.7
                            +
                    Socratic Probe Score (S_logic) × 0.3
                            =
                    Composite Mastery Score

Score ≥ 0.85  →  PASS  →  Mastery hash generated, advance to next concept
0.60 ≤ Score < 0.85  →  HINT  →  Prerequisite-derived hint, retry permitted
Score < 0.60  →  RESET  →  Lesson reset with concept explanation
```

A student who explains backpropagation in their own words — without using the word "gradient" — still passes. Because SAE grades meaning, not vocabulary.

---

## 🔐 Data Sovereignty

```python
# From core_brain.py — enforced at the Python networking layer
class SovereigntyError(Exception):
    pass

# Any HTTP request to a non-localhost endpoint raises SovereigntyError
# No student data can leave the machine — even if a dependency tries
```

---

## 🛠️ Tech Stack

| Category | Technology |
|---|---|
| Agent Orchestration | LangGraph, LangChain |
| Local LLM Inference | Ollama (llama3.2 / Mistral 7B) |
| Semantic Embeddings | Sentence Transformers (all-MiniLM-L6-v2) |
| Vector Database | ChromaDB |
| Knowledge Graph | Neo4j |
| UI Dashboard | Streamlit |
| AI Proctoring | OpenCV |
| Backend Database | PostgreSQL |
| Language | Python 3.10+ |

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- [Ollama](https://ollama.ai) installed and running
- Neo4j (local instance)
- PostgreSQL

### Installation

```bash
# Clone the repo
git clone https://github.com/Rithika-alt/SAE-Sovereign_Autonomous_Education-ITS-.git
cd SAE-Sovereign_Autonomous_Education-ITS-

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Pull the LLM model
ollama pull llama3.2

# Set up environment variables
cp .env.example .env
# Edit .env with your Neo4j and PostgreSQL credentials

# Run the app
streamlit run app.py
```

---

## 📸 Screenshots

| Login & Onboarding | Roadmap Generation |
|---|---|
| ![Login](assets/login.png) | ![Roadmap](assets/roadmap.png) |

| Lesson Content | Knowledge Graph |
|---|---|
| ![Lesson](assets/lesson.png) | ![Graph](assets/knowledge_graph.png) |

| Semantic Grading (PASS) | Mastery Certificate |
|---|---|
| ![Grading](assets/grading.png) | ![Certificate](assets/certificate.png) |

> **Dashboard at Week 10/10 — Advanced Neural Networks pathway (98% mastery, Socratic audit confirmed)**
> ![Full Dashboard](assets/dashboard.png)

---

## 📊 Performance

| Metric | Result |
|---|---|
| Semantic grading agreement with human graders | ~91% (evaluated on 50+ answer pairs) |
| False-fail rate for paraphrase-correct answers | ~3% (vs ~34% for keyword matching baseline) |
| Lesson generation latency (local Ollama) | ~8–15 seconds per lesson |
| Local inference — data sent to external APIs | **0 bytes** |

---

## 📄 Research Paper

This system is the subject of an IEEE conference paper:

> **Sovereign Autonomous Education (SAE): A Local-First, Multi-Agent Intelligent Tutoring System with Semantic Grading, Affective Pacing, and Verifiable Proof-of-Learning**
> Rithika Rajavel,Global Academy of Technology, Bengaluru

*Submitted to IEEE conference proceedings, 2025.*

---

## 👩‍💻 Author

**Rithika Rajavel** — AI & ML Engineering Student, Global Academy of Technology, Bengaluru
- GitHub: [@Rithika-alt](https://github.com/Rithika-alt)
- LinkedIn: [Rithika Rajavel](https://www.linkedin.com/in/rithika-rajavel-420843339/)
- Email: rithikaif09@gmail.com

---

## ⭐ If this project helped you, please give it a star!
