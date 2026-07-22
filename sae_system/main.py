"""CLI entry point for the Sovereign Autonomous Education (SAE) System."""

import argparse
import sys
import os
import uuid

from dotenv import load_dotenv

load_dotenv()

# Ensure the project root is importable when running `python main.py`
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> None:
    """Parse CLI args, initialise state, run the SAE graph, print results."""
    parser = argparse.ArgumentParser(
        description="Sovereign Autonomous Education (SAE) System — CLI runner"
    )
    parser.add_argument(
        "--student_id",
        default="student_01",
        help="Learner identifier (default: student_01)",
    )
    parser.add_argument(
        "--concept_id",
        default="linear_algebra",
        help="Starting concept (default: linear_algebra)",
    )
    parser.add_argument(
        "--domain",
        default="machine_learning",
        help="Subject domain (default: machine_learning)",
    )
    args = parser.parse_args()

    from orchestration.state_schema import GraphState
    from orchestration.state_graph import sae_graph

    session_id = str(uuid.uuid4())

    initial_state: GraphState = GraphState(
        student_id=args.student_id,
        concept_id=args.concept_id,
        domain=args.domain,
        lesson_content="",
        student_response="",
        reference_answer="",
        semantic_score=0.0,
        logic_score=0.0,
        composite_score=0.0,
        mastery_level=0.0,
        cognitive_load_score=0.0,
        response_history=[],
        current_phase="lesson",
        session_id=session_id,
        error_message="",
        next_concept_id="",
        proof_hash="",
    )

    print(f"\nStarting SAE session [{session_id}]")
    print(f"  Student : {args.student_id}")
    print(f"  Concept : {args.concept_id}")
    print(f"  Domain  : {args.domain}")
    print("-" * 60)

    try:
        result = sae_graph.invoke(initial_state)
    except Exception as exc:
        print(f"[ERROR] Graph execution failed: {exc}")
        sys.exit(1)

    print("\n=== SAE Session Result ===")
    print(f"Lesson Content:\n{result.get('lesson_content', '[none]')}\n")
    print(f"Composite Score : {result.get('composite_score', 0.0):.4f}")
    print(f"Current Phase   : {result.get('current_phase', 'unknown')}")
    proof = result.get("proof_hash", "")
    print(f"Proof Hash      : {proof if proof else '[not yet issued]'}")

    if result.get("error_message"):
        print(f"\n[WARNING] {result['error_message']}")

    print("\n" + "=" * 60)
    print("To launch the interactive dashboard, run:")
    print("  streamlit run dashboard/app.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
