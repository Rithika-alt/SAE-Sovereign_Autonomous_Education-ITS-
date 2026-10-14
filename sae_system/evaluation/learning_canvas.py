"""Learning Canvas view model — Phase 10.

Pure data transformation, no Streamlit/Plotly here (Step 22: separate the
visual data model from the rendering layer so it's testable without a
browser). Consumes the existing KnowledgeGraph, progress_store, and
recommendation_engine — does not maintain a second graph, a second mastery
score, or a second recommendation algorithm (Hard Rules 2/3/5).

Status is derived using the exact same threshold constants Phase 8's
diagnose_tutor_state already established (SEMANTIC_PASS_THRESHOLD,
MASTERY_THRESHOLD) — not a new classification system, just the same
thresholds applied per-node instead of only to the current concept.
"""

from __future__ import annotations

from typing import Dict, List, Optional

STATUS_MASTERED = "mastered"
STATUS_DEVELOPING = "developing"
STATUS_WEAK = "weak"
STATUS_AVAILABLE = "available"
STATUS_LOCKED = "locked"


def _node_status(mastery: float, prerequisites_met: bool) -> str:
    from config import SEMANTIC_PASS_THRESHOLD
    from memory.graph_engine import MASTERY_THRESHOLD

    if mastery >= MASTERY_THRESHOLD:
        return STATUS_MASTERED
    if mastery >= SEMANTIC_PASS_THRESHOLD:
        return STATUS_DEVELOPING
    if mastery > 0.0:
        return STATUS_WEAK
    return STATUS_AVAILABLE if prerequisites_met else STATUS_LOCKED


def _current_concept_id(domain_data: Dict) -> Optional[str]:
    """Best-effort: the roadmap's currently-selected module, if any is
    embedded in the passed session snapshot (see build_learning_canvas's
    `current_module_id` param — this function just documents the contract;
    the actual value is threaded straight through, no computation here).
    """
    return domain_data.get("current_module_id")


def build_learning_canvas(
    student_id: str,
    domain: str,
    current_module_id: Optional[str] = None,
) -> Dict:
    """Build the full view model for the Learning Canvas page.

    Returns:
        {
          "domain": str,
          "nodes": [{id, label, mastery, status, is_primary, is_current,
                     week, module_id, domain, prerequisites: [str]}],
          "edges": [{source, target}],
          "current_concept_id": str | None,
          "recommendations": [...],       # from recommendation_engine, as-is
          "top_recommendation": {...} | None,
          "recommended_path": [str],      # node ids: current -> ... -> recommended
          "insufficient_data": bool,      # true if domain has no graph data yet
        }
    """
    from memory.graph_engine import KnowledgeGraph
    from evaluation.recommendation_engine import recommend_next_actions

    graph = KnowledgeGraph(student_id=student_id)
    data = graph.get_graph_data_by_domain(domain) if domain else graph.get_graph_data()
    raw_nodes = data.get("nodes", [])
    raw_edges = data.get("edges", [])

    if not raw_nodes:
        return {
            "domain": domain,
            "nodes": [],
            "edges": [],
            "current_concept_id": current_module_id,
            "recommendations": [],
            "top_recommendation": None,
            "recommended_path": [],
            "insufficient_data": True,
        }

    prereqs_by_target: Dict[str, List[str]] = {}
    for e in raw_edges:
        prereqs_by_target.setdefault(e["target"], []).append(e["source"])

    nodes = []
    for n in raw_nodes:
        nid = n["id"]
        mastery = n.get("mastery") or 0.0
        prereq_ids = prereqs_by_target.get(nid, [])
        prereqs_met = graph.prerequisites_met(nid) if prereq_ids else True
        nodes.append({
            "id": nid,
            "label": nid.replace("_", " ").title(),
            "mastery": mastery,
            "status": _node_status(mastery, prereqs_met),
            "is_primary": n.get("is_primary", False),
            "is_current": nid == current_module_id,
            "week": n.get("week", 0),
            "module_id": n.get("module_id", ""),
            "domain": n.get("domain", domain),
            "prerequisites": prereq_ids,
        })

    edges = [{"source": e["source"], "target": e["target"]} for e in raw_edges]

    recommendations = recommend_next_actions(student_id, max_recommendations=3)
    # Only keep recommendations that are actually about this domain's graph —
    # recommend_next_actions can span multiple enrolled domains.
    domain_recs = [r for r in recommendations if r.get("domain") in (domain, None)] or recommendations
    top = domain_recs[0] if domain_recs else None

    recommended_path: List[str] = []
    if top and top.get("concept_id") and current_module_id:
        target = top["concept_id"]
        node_ids = {n["id"] for n in nodes}
        if current_module_id in node_ids and target in node_ids:
            if current_module_id == target:
                recommended_path = [current_module_id]
            else:
                # Direct-prerequisite hop if adjacent; otherwise just the
                # two endpoints — this is a visual hint, not a full
                # pathfinding claim the graph doesn't actually support
                # for non-adjacent nodes.
                target_prereqs = prereqs_by_target.get(target, [])
                if current_module_id in target_prereqs:
                    recommended_path = [current_module_id, target]
                else:
                    recommended_path = [current_module_id, target]

    return {
        "domain": domain,
        "nodes": nodes,
        "edges": edges,
        "current_concept_id": current_module_id,
        "recommendations": domain_recs,
        "top_recommendation": top,
        "recommended_path": recommended_path,
        "insufficient_data": False,
    }


def get_concept_detail(canvas: Dict, concept_id: str) -> Optional[Dict]:
    """Look up one node's full detail from an already-built canvas, plus
    its prerequisite nodes' own status (for the contextual panel's
    prerequisite checklist — Step 10).
    """
    node = next((n for n in canvas["nodes"] if n["id"] == concept_id), None)
    if node is None:
        return None

    nodes_by_id = {n["id"]: n for n in canvas["nodes"]}
    prereq_details = [
        {"id": pid, "label": nodes_by_id[pid]["label"], "status": nodes_by_id[pid]["status"],
         "mastery": nodes_by_id[pid]["mastery"]}
        for pid in node["prerequisites"] if pid in nodes_by_id
    ]

    concept_recs = [r for r in canvas["recommendations"] if r.get("concept_id") == concept_id]

    return {
        **node,
        "prerequisite_details": prereq_details,
        "recommendation": concept_recs[0] if concept_recs else None,
    }
