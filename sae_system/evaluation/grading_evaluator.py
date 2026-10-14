"""Evaluates SAE's own grading pipelines against a hand-labeled gold-standard set.

Answers "is the AI grader itself accurate?" — a different question from
"did this particular student pass this particular test." Runs the semantic
grader (evaluation/semantic_auditor.grade_response) and the exact-match
grader (evaluation/test_engine.grade_test) against known-correct labels and
reports precision/recall/F1/accuracy by hand (no sklearn dependency).

Also directly measures the SEMANTIC_PASS_THRESHOLD inconsistency: test_engine.py
and auditor_agent.py/state_graph.py historically read the same env var with
different coded defaults (0.45 vs 0.85). compare_thresholds() reports how many
gold-set verdicts actually flip between the two values, turning that from a
prose observation into a number.

Runnable standalone: python -m evaluation.grading_evaluator
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

DEFAULT_GOLD_SET_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "eval" / "grading_gold_set.json"
)


def load_gold_set(path: Path = DEFAULT_GOLD_SET_PATH) -> Dict[str, List[Dict]]:
    """Load the gold-standard set. Returns {"short_answer": [...], "mcq": [...], "true_false": [...]}."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return {
        "short_answer": data.get("short_answer", []),
        "mcq": data.get("mcq", []),
        "true_false": data.get("true_false", []),
    }


def _prf1(tp: int, fp: int, tn: int, fn: int) -> Dict[str, float]:
    """Compute precision/recall/F1/accuracy by hand, guarding div-by-zero."""
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    total = tp + fp + tn + fn
    accuracy = (tp + tn) / total if total > 0 else 0.0
    return {
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
        "n": total,
    }


def evaluate_semantic_grader(gold_set: List[Dict], threshold: float) -> Dict:
    """Run every short_answer item through grade_response() and score against expected_label.

    "pass" is the positive class: TP = grader says pass and gold says pass, etc.
    """
    from evaluation.semantic_auditor import grade_response

    tp = fp = tn = fn = 0
    per_item: List[Dict] = []

    for item in gold_set:
        score = grade_response(item["candidate_answer"], item["reference_answer"])
        predicted = "pass" if score >= threshold else "fail"
        expected = item["expected_label"]

        if predicted == "pass" and expected == "pass":
            tp += 1
        elif predicted == "pass" and expected == "fail":
            fp += 1
        elif predicted == "fail" and expected == "fail":
            tn += 1
        else:
            fn += 1

        per_item.append({
            "id": item["id"],
            "case": item.get("case", ""),
            "similarity": round(score, 4),
            "predicted": predicted,
            "expected": expected,
            "correct": predicted == expected,
        })

    metrics = _prf1(tp, fp, tn, fn)
    metrics["threshold"] = threshold
    metrics["per_item"] = per_item
    return metrics


def compare_thresholds(
    gold_set: List[Dict], thresholds: Tuple[float, float] = (0.45, 0.85)
) -> Dict:
    """Run evaluate_semantic_grader at both thresholds and report where verdicts diverge.

    This is the concrete, numeric surfacing of the SEMANTIC_PASS_THRESHOLD
    inconsistency between test_engine.py (historically defaulted 0.45) and
    auditor_agent.py/state_graph.py (historically defaulted 0.85).
    """
    t1, t2 = thresholds
    result_t1 = evaluate_semantic_grader(gold_set, t1)
    result_t2 = evaluate_semantic_grader(gold_set, t2)

    by_id_t2 = {item["id"]: item for item in result_t2["per_item"]}
    disagreements = []
    for item_t1 in result_t1["per_item"]:
        item_t2 = by_id_t2[item_t1["id"]]
        if item_t1["predicted"] != item_t2["predicted"]:
            disagreements.append({
                "id": item_t1["id"],
                "case": item_t1["case"],
                "similarity": item_t1["similarity"],
                "expected": item_t1["expected"],
                f"predicted_at_{t1}": item_t1["predicted"],
                f"predicted_at_{t2}": item_t2["predicted"],
            })

    n = len(gold_set)
    return {
        "threshold_a": {"value": t1, "metrics": result_t1},
        "threshold_b": {"value": t2, "metrics": result_t2},
        "disagreement_count": len(disagreements),
        "disagreement_pct": round(len(disagreements) / n * 100, 1) if n else 0.0,
        "disagreement_items": disagreements,
    }


def evaluate_by_category(gold_set: List[Dict], threshold: float) -> Dict[str, Dict]:
    """Break evaluate_semantic_grader's per-item results down by the gold
    set's `case` tag — Phase 9 Step 5's "measure where semantic grading
    succeeds and fails," not just an aggregate number.
    """
    result = evaluate_semantic_grader(gold_set, threshold)
    by_case: Dict[str, List[Dict]] = {}
    for item in result["per_item"]:
        by_case.setdefault(item["case"], []).append(item)

    breakdown: Dict[str, Dict] = {}
    for case, items in sorted(by_case.items()):
        correct = sum(1 for i in items if i["correct"])
        breakdown[case] = {
            "n": len(items),
            "accuracy": round(correct / len(items), 4) if items else 0.0,
            "mean_similarity": round(sum(i["similarity"] for i in items) / len(items), 4) if items else 0.0,
            "misclassified_ids": [i["id"] for i in items if not i["correct"]],
        }
    return breakdown


def sweep_thresholds(gold_set: List[Dict], thresholds: List[float]) -> List[Dict]:
    """Full threshold sweep (Phase 9 Step 6) — one metrics row per threshold,
    without the per-item detail evaluate_semantic_grader returns (kept out
    to keep sweep output compact across many thresholds).
    """
    rows = []
    for t in thresholds:
        m = evaluate_semantic_grader(gold_set, t)
        rows.append({
            "threshold": t, "accuracy": m["accuracy"], "precision": m["precision"],
            "recall": m["recall"], "f1": m["f1"],
            "tp": m["tp"], "fp": m["fp"], "tn": m["tn"], "fn": m["fn"],
        })
    return rows


def evaluate_mcq_tf_pipeline(gold_set: Dict[str, List[Dict]]) -> Dict:
    """Completeness check: run mcq/true_false items through TestEngine.grade_test's
    exact-match path and confirm the predicted pass/fail matches expected_label.
    """
    from evaluation.test_engine import TestEngine

    engine = TestEngine()
    tp = fp = tn = fn = 0
    per_item: List[Dict] = []

    for bucket in ("mcq", "true_false"):
        for item in gold_set.get(bucket, []):
            question = {
                "question_id": item["id"],
                "question": item["question"],
                "type": bucket,
                "options": item.get("options", ["True", "False"] if bucket == "true_false" else []),
                "correct_answer": item["correct_answer"],
                "explanation": "",
                "marks": item.get("marks", 1),
                "difficulty": item.get("difficulty", "medium"),
            }
            result = engine.grade_test([question], {item["id"]: item["student_answer"]})
            is_correct = result["results"][0]["is_correct"]
            predicted = "pass" if is_correct else "fail"
            expected = item["expected_label"]

            if predicted == "pass" and expected == "pass":
                tp += 1
            elif predicted == "pass" and expected == "fail":
                fp += 1
            elif predicted == "fail" and expected == "fail":
                tn += 1
            else:
                fn += 1

            per_item.append({
                "id": item["id"], "type": bucket,
                "predicted": predicted, "expected": expected,
                "correct": predicted == expected,
            })

    metrics = _prf1(tp, fp, tn, fn)
    metrics["per_item"] = per_item
    return metrics


def _print_report(gold_set: Dict[str, List[Dict]]) -> None:
    print("=" * 70)
    print("SAE Grading Pipeline Evaluation")
    print("=" * 70)

    sa_set = gold_set["short_answer"]
    print(f"\nGold set: {len(sa_set)} short_answer, {len(gold_set['mcq'])} mcq, "
          f"{len(gold_set['true_false'])} true_false items\n")

    comparison = compare_thresholds(sa_set, thresholds=(0.45, 0.85))
    for label in ("threshold_a", "threshold_b"):
        m = comparison[label]["metrics"]
        t = comparison[label]["value"]
        print(f"--- Semantic grader @ threshold={t} (N={m['n']}) ---")
        print(f"  Accuracy:  {m['accuracy']:.1%}")
        print(f"  Precision: {m['precision']:.1%}")
        print(f"  Recall:    {m['recall']:.1%}")
        print(f"  F1:        {m['f1']:.1%}")
        print(f"  TP={m['tp']} FP={m['fp']} TN={m['tn']} FN={m['fn']}\n")

    print(f"--- Threshold disagreement (0.45 vs 0.85) ---")
    print(f"  {comparison['disagreement_count']} / {len(sa_set)} items "
          f"({comparison['disagreement_pct']}%) flip pass/fail depending on which threshold is used.")
    if comparison["disagreement_items"]:
        print("  Disagreeing items:")
        for d in comparison["disagreement_items"]:
            print(f"    [{d['case']}] {d['id']}: sim={d['similarity']} "
                  f"expected={d['expected']} -> 0.45={d['predicted_at_0.45']} 0.85={d['predicted_at_0.85']}")

    print("\n--- MCQ / True-False exact-match completeness check ---")
    mcq_tf = evaluate_mcq_tf_pipeline(gold_set)
    print(f"  Accuracy: {mcq_tf['accuracy']:.1%} (N={mcq_tf['n']}) "
          f"TP={mcq_tf['tp']} FP={mcq_tf['fp']} TN={mcq_tf['tn']} FN={mcq_tf['fn']}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    import sys
    from pathlib import Path as _Path

    sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    _gold = load_gold_set()
    _print_report(_gold)
