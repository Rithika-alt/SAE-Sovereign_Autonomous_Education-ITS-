"""
Diagnostic script for test generation failures.
Run from: SAE_SYSTEM/sae_system/
  python tests/diagnose_test_generation.py
"""

import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

SEP = "-" * 60

def section(title):
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)

# ---------------------------------------------------------------------------
# 1. Environment
# ---------------------------------------------------------------------------
section("1. Environment variables")
base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
model    = os.getenv("OLLAMA_MODEL", "llama3.2")
print(f"  OLLAMA_BASE_URL : {base_url}")
print(f"  OLLAMA_MODEL    : {model}")

# ---------------------------------------------------------------------------
# 2. Ollama reachability
# ---------------------------------------------------------------------------
section("2. Ollama reachability")
import urllib.request, urllib.error
try:
    with urllib.request.urlopen(f"{base_url}/api/tags", timeout=5) as r:
        data = json.loads(r.read())
        models = [m["name"] for m in data.get("models", [])]
        print(f"  Ollama is UP. Available models: {models}")
        if not any(model in m for m in models):
            print(f"  WARNING: '{model}' not in model list — generation will fail!")
        else:
            print(f"  OK: '{model}' found.")
except Exception as e:
    print(f"  FAIL: Cannot reach Ollama at {base_url} — {e}")
    print("  Cannot continue — start Ollama first.")
    sys.exit(1)

# ---------------------------------------------------------------------------
# 3. Simulate lesson content (what app.py passes)
# ---------------------------------------------------------------------------
section("3. Simulated lesson content")

CONCEPT = "neural_networks"
DOMAIN  = "Artificial Intelligence"

# Try to load from file cache first (mirrors what the tutor agent would return)
from pathlib import Path
cache_file = Path("./data/lessons") / f"{DOMAIN.lower().replace(' ', '_')}_{CONCEPT.lower().replace(' ', '_')}.json"
lesson_dict = {}
if cache_file.exists():
    with cache_file.open() as f:
        lesson_dict = json.load(f)
    print(f"  Loaded lesson from cache: {cache_file}")
else:
    print(f"  No cached lesson at {cache_file}")
    print("  Using synthetic lesson content for diagnosis.")
    lesson_dict = {
        "introduction": "Neural networks are computational models inspired by the human brain. They consist of layers of nodes (neurons) connected by weighted edges. They are fundamental to modern machine learning and AI.",
        "theory": "A neural network processes inputs through layers: input, hidden, and output. Each connection has a weight adjusted during training via backpropagation using gradient descent.",
        "example": "Example: Train a network to classify images. Input: pixel values. Hidden layers: feature detectors. Output: class probabilities. Training adjusts weights to minimize cross-entropy loss.",
        "misconceptions": "1. Misconception: Neural networks mimic the brain exactly. Correction: They are loosely inspired by biology but operate very differently.\n2. Misconception: More layers always means better results. Correction: Too many layers cause overfitting or vanishing gradients.\n3. Misconception: Neural networks require huge data. Correction: Transfer learning works well with small datasets.",
        "applications": "1. Computer Vision: Image classification, object detection, face recognition.\n2. Natural Language Processing: Sentiment analysis, translation, text generation.",
        "summary": "1. Neural networks learn patterns from data using layered computation.\n2. Backpropagation and gradient descent are the core training mechanisms.\n3. They power most modern AI applications from vision to language.",
    }

lesson_content = "\n\n".join(
    str(lesson_dict.get(k, ""))
    for k in ["introduction", "theory", "example", "misconceptions", "applications", "summary"]
    if lesson_dict.get(k)
)[:3000]

print(f"  lesson_content length : {len(lesson_content)} chars")
if not lesson_content.strip():
    print("  ERROR: lesson_content is EMPTY — this is why tests won't generate.")
    print("  The lesson dict keys present:", list(lesson_dict.keys()))
else:
    print(f"  First 200 chars: {lesson_content[:200]!r}")

# ---------------------------------------------------------------------------
# 4. Direct Ollama call (raw)
# ---------------------------------------------------------------------------
section("4. Direct Ollama call via ChatOllama")
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage

system_prompt = (
    f"Generate a 10-question test for the concept '{CONCEPT}' in '{DOMAIN}'. "
    "Return ONLY valid JSON as a list of question objects:\n"
    "[\n"
    "  {\n"
    '    "question_id": "q1",\n'
    '    "question": "Question text here",\n'
    '    "type": "mcq",\n'
    '    "options": ["A", "B", "C", "D"],\n'
    '    "correct_answer": "A",\n'
    '    "explanation": "Why this answer is correct.",\n'
    '    "marks": 2,\n'
    '    "difficulty": "medium"\n'
    "  }\n"
    "]\n"
    "Include exactly: 4 MCQ (type=mcq, 4 options, marks=2), "
    "3 true/false (type=true_false, marks=1), "
    "3 short answer (type=short_answer, no options, marks=5). "
    "Base questions on:\n\n"
    + lesson_content[:1000]
)

llm = ChatOllama(base_url=base_url, model=model, temperature=0.5)
print(f"  Sending prompt ({len(system_prompt)} chars) to Ollama…")
t0 = time.time()
try:
    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Generate the test for: {CONCEPT}"),
    ])
    elapsed = time.time() - t0
    raw = response.content
    print(f"  Ollama responded in {elapsed:.1f}s — {len(raw)} chars")
    print(f"  First 500 chars of response:\n{raw[:500]}")
    OLLAMA_RAW = raw
except Exception as e:
    print(f"  FAIL: Ollama call raised {type(e).__name__}: {e}")
    OLLAMA_RAW = None

# ---------------------------------------------------------------------------
# 5. JSON extraction
# ---------------------------------------------------------------------------
section("5. JSON extraction (_extract_json_list)")
if OLLAMA_RAW is None:
    print("  Skipped — no Ollama response.")
else:
    from evaluation.test_engine import _extract_json_list
    try:
        questions = _extract_json_list(OLLAMA_RAW)
        print(f"  Extracted {len(questions)} question dicts.")
        if questions:
            print(f"  First question: {json.dumps(questions[0], indent=2)}")
        EXTRACTED = questions
    except ValueError as e:
        print(f"  FAIL: _extract_json_list raised ValueError: {e}")
        print(f"  Full raw response:\n{OLLAMA_RAW}")
        EXTRACTED = []

# ---------------------------------------------------------------------------
# 6. Normalisation
# ---------------------------------------------------------------------------
section("6. Normalisation (_normalise_question)")
if not OLLAMA_RAW:
    print("  Skipped.")
elif not EXTRACTED:
    print("  Skipped — no extracted questions.")
else:
    from evaluation.test_engine import _normalise_question
    normalised = [_normalise_question(q, i) for i, q in enumerate(EXTRACTED[:10])]
    print(f"  Normalised {len(normalised)} questions.")
    type_counts = {}
    for q in normalised:
        type_counts[q["type"]] = type_counts.get(q["type"], 0) + 1
    print(f"  Type distribution: {type_counts}")
    total_marks = sum(q["marks"] for q in normalised)
    print(f"  Total marks: {total_marks}")
    for q in normalised:
        ok = bool(q["correct_answer"])
        print(f"  {q['question_id']} [{q['type']}] marks={q['marks']} correct_answer={'OK' if ok else 'EMPTY!'}")

# ---------------------------------------------------------------------------
# 7. Full TestEngine.generate_test end-to-end
# ---------------------------------------------------------------------------
section("7. Full TestEngine.generate_test end-to-end")
from evaluation.test_engine import TestEngine
engine = TestEngine()
print(f"  Calling engine.generate_test('{CONCEPT}', '{DOMAIN}', lesson_content)…")
t0 = time.time()
questions = engine.generate_test(CONCEPT, DOMAIN, lesson_content)
elapsed = time.time() - t0
print(f"  Completed in {elapsed:.1f}s — got {len(questions)} questions.")
type_counts = {}
for q in questions:
    type_counts[q["type"]] = type_counts.get(q["type"], 0) + 1
print(f"  Type distribution: {type_counts}")
total_marks = sum(q["marks"] for q in questions)
print(f"  Total marks: {total_marks}")
print("\n  Sample question:")
print(json.dumps(questions[0], indent=4))

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
section("SUMMARY")
issues = []
if not lesson_content.strip():
    issues.append("lesson_content is EMPTY — tutor agent lesson never stored in session state")
if OLLAMA_RAW is None:
    issues.append("Ollama call failed — check if Ollama is running and model is loaded")
elif OLLAMA_RAW and not EXTRACTED:
    issues.append("JSON extraction failed — Ollama response was not valid JSON")
if len(questions) == 10 and all(q["question_id"].startswith("q") for q in questions):
    fallback_used = all("best describes" in q["question"] for q in questions if q["type"] == "mcq")
    if fallback_used:
        issues.append("Fallback questions used — Ollama generation failed upstream")

if issues:
    print("  ISSUES FOUND:")
    for i, issue in enumerate(issues, 1):
        print(f"    {i}. {issue}")
else:
    print("  All checks passed — test generation pipeline is working correctly.")
    print(f"  Generated {len(questions)} questions with {total_marks} total marks.")
