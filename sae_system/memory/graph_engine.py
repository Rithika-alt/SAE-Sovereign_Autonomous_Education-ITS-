"""Knowledge graph engine — per-student, persistent, dynamically populated."""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import networkx as nx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

USE_NEO4J: bool = os.getenv("USE_NEO4J", "false").lower() == "true"
MASTERY_THRESHOLD: float = 0.85


def _normalize_concept(c) -> str:
    """Return a plain string from a concept entry that may be a str or dict.

    The LLM occasionally returns concepts as dicts e.g. {"concept": "API Design"}.
    This helper extracts the name so callers can always do .lower() safely.
    """
    if isinstance(c, str):
        return c
    if isinstance(c, dict):
        for key in ("concept", "name", "title", "topic", "id"):
            if key in c:
                return str(c[key])
        return str(next(iter(c.values()), "unknown"))
    return str(c)


class KnowledgeGraph:
    """Directed knowledge graph tracking concept mastery for one student.

    Each student gets their own graph file at ./data/knowledge_graphs/{student_id}.json.
    The graph is loaded on construction and auto-saved after every mutation.

    Backends:
        NetworkX (default, USE_NEO4J=false) — file-persisted JSON
        Neo4j    (USE_NEO4J=true)           — bolt connection
    """

    def __init__(self, student_id: str = "default") -> None:
        self._student_id = student_id
        self._persistence_dir = Path("./data/knowledge_graphs")
        self._persistence_dir.mkdir(parents=True, exist_ok=True)
        self._persistence_file = self._persistence_dir / f"{student_id}.json"

        if USE_NEO4J:
            try:
                self._backend = "neo4j"
                self._init_neo4j()
            except Exception as exc:
                logger.warning(
                    "Neo4j unavailable (%s) — falling back to NetworkX for student '%s'",
                    exc, student_id,
                )
                self._backend = "networkx"
                self._graph: nx.DiGraph = nx.DiGraph()
                self._load()
        else:
            self._backend = "networkx"
            self._graph: nx.DiGraph = nx.DiGraph()
            self._load()

    # ------------------------------------------------------------------
    # Backend initialisation
    # ------------------------------------------------------------------

    def _init_neo4j(self) -> None:
        from neo4j import GraphDatabase
        uri      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
        user     = os.getenv("NEO4J_USER",     "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "saesystem")
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        # Create indexes — wrapped individually so one failure doesn't abort init
        for cypher in (
            "CREATE INDEX concept_student IF NOT EXISTS FOR (c:Concept) ON (c.student)",
            "CREATE INDEX module_student IF NOT EXISTS FOR (m:Module) ON (m.student)",
            "CREATE INDEX domain_student IF NOT EXISTS FOR (d:Domain) ON (d.student)",
        ):
            try:
                with self._driver.session() as session:
                    session.run(cypher)
            except Exception as idx_exc:
                logger.debug("Index creation skipped (%s): %s", cypher[:40], idx_exc)
        # Auto-migrate JSON → Neo4j if Neo4j is empty but a JSON file exists
        with self._driver.session() as session:
            count = session.run(
                "MATCH (c:Concept {student: $sid}) RETURN count(c) AS cnt",
                sid=self._student_id,
            ).single()["cnt"]
        if count == 0 and self._persistence_file.exists():
            self._migrate_json_to_neo4j()

    def _migrate_json_to_neo4j(self) -> None:
        """One-time import of existing JSON knowledge graph into Neo4j."""
        try:
            with self._persistence_file.open() as f:
                data = json.load(f)
            with self._driver.session() as session:
                for node in data.get("nodes", []):
                    session.run(
                        "MERGE (c:Concept {id: $cid, student: $sid}) "
                        "ON CREATE SET c.mastery = 0.0 "
                        "SET c.domain=$domain, c.is_primary=$is_primary, "
                        "    c.module_id=$module_id, c.week=$week, "
                        "    c.mastery=coalesce($mastery, 0.0), c.last_reviewed=$lr",
                        cid=node["concept_id"], sid=self._student_id,
                        domain=node.get("domain", ""),
                        is_primary=node.get("is_primary", False),
                        module_id=node.get("module_id", ""),
                        week=node.get("week", 0),
                        mastery=node.get("mastery") or 0.0,
                        lr=node.get("last_reviewed"),
                    )
                for edge in data.get("edges", []):
                    session.run(
                        "MATCH (p:Concept {id: $src, student: $sid}), "
                        "      (c:Concept {id: $dst, student: $sid}) "
                        "MERGE (p)-[:PREREQUISITE_OF]->(c)",
                        src=edge["from_concept"], dst=edge["to_concept"],
                        sid=self._student_id,
                    )
            logger.info(
                "Migrated %d nodes from JSON → Neo4j for student '%s'",
                len(data.get("nodes", [])), self._student_id,
            )
        except Exception as exc:
            logger.warning("JSON→Neo4j migration failed: %s", exc)

    # ------------------------------------------------------------------
    # Persistence (NetworkX only)
    # ------------------------------------------------------------------

    def _save(self) -> None:
        """Serialise the NetworkX graph to the student's JSON file."""
        if self._backend != "networkx":
            return
        nodes = [
            {
                "concept_id":    n,
                "domain":        self._graph.nodes[n].get("domain", ""),
                "mastery":       self._graph.nodes[n].get("mastery", 0.0),
                "last_reviewed": self._graph.nodes[n].get("last_reviewed"),
                "is_primary":    self._graph.nodes[n].get("is_primary", False),
                "module_id":     self._graph.nodes[n].get("module_id", ""),
                "week":          self._graph.nodes[n].get("week", 0),
            }
            for n in self._graph.nodes
        ]
        edges = [
            {"from_concept": u, "to_concept": v}
            for u, v in self._graph.edges
        ]
        payload = {
            "student_id": self._student_id,
            "last_saved": datetime.utcnow().isoformat(),
            "nodes": nodes,
            "edges": edges,
        }
        try:
            with self._persistence_file.open("w") as f:
                json.dump(payload, f, indent=2)
        except Exception as exc:
            logger.warning("KnowledgeGraph _save failed for %s: %s", self._student_id, exc)

    def _load(self) -> None:
        """Load the student's graph from JSON. Silent no-op if file missing."""
        if not self._persistence_file.exists():
            return
        try:
            with self._persistence_file.open() as f:
                data = json.load(f)
            for node in data.get("nodes", []):
                cid = node["concept_id"]
                self._graph.add_node(
                    cid,
                    domain=node.get("domain", ""),
                    mastery=node.get("mastery") or 0.0,
                    last_reviewed=node.get("last_reviewed"),
                    is_primary=node.get("is_primary", False),
                    module_id=node.get("module_id", ""),
                    week=node.get("week", 0),
                )
            for edge in data.get("edges", []):
                src, dst = edge["from_concept"], edge["to_concept"]
                if src in self._graph and dst in self._graph:
                    self._graph.add_edge(src, dst)
            logger.info(
                "KnowledgeGraph loaded %d nodes, %d edges for student '%s'",
                self._graph.number_of_nodes(),
                self._graph.number_of_edges(),
                self._student_id,
            )
        except Exception as exc:
            logger.warning(
                "KnowledgeGraph _load failed for %s (%s) — starting empty.",
                self._student_id, exc,
            )
            self._graph = nx.DiGraph()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_concept(
        self,
        concept_id: str,
        domain: str,
        prerequisites: Optional[List[str]] = None,
        is_primary: bool = False,
        module_id: str = "",
        week: int = 0,
        _skip_save: bool = False,
    ) -> None:
        """Add or update a concept node and wire prerequisite edges.

        Idempotent: if the node already exists, attributes are updated but
        mastery is never reset. Pass _skip_save=True when the caller
        (e.g. populate_from_roadmap) handles the single _save() call itself.
        """
        if prerequisites is None:
            prerequisites = []

        if self._backend == "networkx":
            if concept_id in self._graph:
                self._graph.nodes[concept_id].update({
                    "domain":     domain,
                    "is_primary": is_primary,
                    "module_id":  module_id,
                    "week":       week,
                })
            else:
                self._graph.add_node(
                    concept_id,
                    domain=domain,
                    mastery=0.0,
                    last_reviewed=None,
                    is_primary=is_primary,
                    module_id=module_id,
                    week=week,
                )
            for prereq in prerequisites:
                if not self._graph.has_edge(prereq, concept_id):
                    self._graph.add_edge(prereq, concept_id)
            if not _skip_save:
                self._save()
        else:
            with self._driver.session() as session:
                session.run(
                    "MERGE (c:Concept {id: $cid, student: $sid}) "
                    "ON CREATE SET c.mastery = 0.0, c.last_reviewed = null "
                    "SET c.domain=$domain, c.is_primary=$is_primary, "
                    "    c.module_id=$module_id, c.week=$week",
                    cid=concept_id, sid=self._student_id,
                    domain=domain, is_primary=is_primary,
                    module_id=module_id, week=week,
                )
                for prereq in prerequisites:
                    session.run(
                        "MERGE (p:Concept {id: $pid, student: $sid}) "
                        "MERGE (c:Concept {id: $cid, student: $sid}) "
                        "MERGE (p)-[:PREREQUISITE_OF]->(c)",
                        pid=prereq, cid=concept_id, sid=self._student_id,
                    )

    def update_mastery(self, concept_id: str, score: float) -> None:
        """Update mastery for a concept (clamped 0–1). Always persists."""
        score = max(0.0, min(1.0, score))
        if self._backend == "networkx":
            if concept_id not in self._graph:
                self._graph.add_node(
                    concept_id,
                    domain="unknown",
                    mastery=score,
                    last_reviewed=datetime.utcnow().isoformat(),
                    is_primary=False,
                    module_id="",
                    week=0,
                )
            else:
                self._graph.nodes[concept_id]["mastery"] = score
                self._graph.nodes[concept_id]["last_reviewed"] = datetime.utcnow().isoformat()
            self._save()
        else:
            with self._driver.session() as session:
                session.run(
                    "MERGE (c:Concept {id: $cid, student: $sid}) "
                    "SET c.mastery=$score, c.last_reviewed=$ts",
                    cid=concept_id, sid=self._student_id,
                    score=score, ts=datetime.utcnow().isoformat(),
                )

    def get_mastery(self, concept_id: str) -> float:
        if self._backend == "networkx":
            m = self._graph.nodes.get(concept_id, {}).get("mastery")
            return float(m) if m is not None else 0.0
        else:
            with self._driver.session() as session:
                result = session.run(
                    "MATCH (c:Concept {id: $cid, student: $sid}) RETURN c.mastery AS m",
                    cid=concept_id, sid=self._student_id,
                )
                record = result.single()
                return float(record["m"]) if record and record["m"] is not None else 0.0

    def get_prerequisites(self, concept_id: str) -> List[str]:
        if self._backend == "networkx":
            return list(self._graph.predecessors(concept_id))
        else:
            with self._driver.session() as session:
                result = session.run(
                    "MATCH (p)-[:PREREQUISITE_OF]->(c:Concept {id: $cid, student: $sid}) "
                    "RETURN p.id AS pid",
                    cid=concept_id, sid=self._student_id,
                )
                return [r["pid"] for r in result]

    def prerequisites_met(self, concept_id: str) -> bool:
        return all(
            self.get_mastery(p) >= MASTERY_THRESHOLD
            for p in self.get_prerequisites(concept_id)
        )

    def get_next_recommended_nodes(self, concept_id: str) -> List[str]:
        if self._backend == "networkx":
            return [
                s for s in self._graph.successors(concept_id)
                if self.prerequisites_met(s)
            ]
        else:
            with self._driver.session() as session:
                result = session.run(
                    "MATCH (c:Concept {id: $cid, student: $sid})-[:PREREQUISITE_OF]->(n) "
                    "RETURN n.id AS nid",
                    cid=concept_id, sid=self._student_id,
                )
                candidates = [r["nid"] for r in result]
            return [c for c in candidates if self.prerequisites_met(c)]

    def get_graph_data(self) -> Dict[str, Any]:
        """Return nodes and edges as serialisable dicts for visualisation."""
        if self._backend == "networkx":
            nodes = [
                {
                    "id":            n,
                    "domain":        self._graph.nodes[n].get("domain", ""),
                    "mastery":       self._graph.nodes[n].get("mastery", 0.0),
                    "last_reviewed": self._graph.nodes[n].get("last_reviewed"),
                    "is_primary":    self._graph.nodes[n].get("is_primary", False),
                    "module_id":     self._graph.nodes[n].get("module_id", ""),
                    "week":          self._graph.nodes[n].get("week", 0),
                }
                for n in self._graph.nodes
            ]
            edges = [{"source": u, "target": v} for u, v in self._graph.edges]
            return {"nodes": nodes, "edges": edges}
        else:
            with self._driver.session() as session:
                node_result = session.run(
                    "MATCH (c:Concept {student: $sid}) "
                    "RETURN c.id AS id, c.domain AS domain, c.mastery AS mastery, "
                    "       c.is_primary AS is_primary, c.module_id AS module_id, c.week AS week",
                    sid=self._student_id,
                )
                nodes = [
                    {
                        "id":         r["id"],
                        "domain":     r["domain"],
                        "mastery":    r["mastery"] or 0.0,
                        "is_primary": r["is_primary"] or False,
                        "module_id":  r["module_id"] or "",
                        "week":       r["week"] or 0,
                    }
                    for r in node_result
                ]
                edge_result = session.run(
                    "MATCH (p)-[:PREREQUISITE_OF]->(c:Concept {student: $sid}) "
                    "RETURN p.id AS source, c.id AS target",
                    sid=self._student_id,
                )
                edges = [{"source": r["source"], "target": r["target"]} for r in edge_result]
            return {"nodes": nodes, "edges": edges}

    # ------------------------------------------------------------------
    # Bulk population from roadmap
    # ------------------------------------------------------------------

    def populate_from_roadmap(self, roadmap: Dict) -> None:
        """Populate the graph from a RoadmapAgent roadmap dict.

        Applies four connection rules:
          Rule 1: concepts within a module form a chain (c[0]→c[1]→…)
          Rule 2: last concept of module N → first concept of module N+1
          Rule 3: last concept of each explicit prerequisite module →
                  first concept of current module
          Rule 4: concepts[0] of each module is marked is_primary=True

        Idempotent — safe to call twice on the same roadmap.
        All add_concept calls pass _skip_save=True; one _save() at the end.
        """
        domain  = roadmap.get("domain", "")
        modules = roadmap.get("modules", [])

        # Step 0 — pre-build module_id → [clean_concept_id] lookup before any loop
        module_concepts: Dict[str, List[str]] = {}
        for mod in modules:
            mid = mod.get("module_id", "")
            module_concepts[mid] = [
                _normalize_concept(c).lower().replace(" ", "_")[:50]
                for c in mod.get("concepts", [])
            ]

        # Step 1 — add all nodes (caller owns the single _save)
        for mod in modules:
            mid  = mod.get("module_id", "")
            week = mod.get("week", 0)
            for j, cid in enumerate(module_concepts.get(mid, [])):
                self.add_concept(
                    concept_id=cid,
                    domain=domain,
                    is_primary=(j == 0),
                    module_id=mid,
                    week=week,
                    _skip_save=True,
                )

        # Step 2 — add all edges
        prev_concepts: List[str] = []
        for mod in modules:
            mid          = mod.get("module_id", "")
            cur_concepts = module_concepts.get(mid, [])
            if not cur_concepts:
                prev_concepts = []
                continue

            # Rule 1: intra-module sequential chain
            for j in range(len(cur_concepts) - 1):
                self._add_edge_safe(cur_concepts[j], cur_concepts[j + 1])

            # Rule 2: last concept of previous module → first of current
            if prev_concepts:
                self._add_edge_safe(prev_concepts[-1], cur_concepts[0])

            # Rule 3: explicit module-level prerequisites
            for prereq_mid in mod.get("prerequisites", []):
                prereq_concepts = module_concepts.get(prereq_mid, [])
                if prereq_concepts:
                    self._add_edge_safe(prereq_concepts[-1], cur_concepts[0])

            prev_concepts = cur_concepts

        # Step 3 — single save after all mutations
        self._save()
        n_nodes = self._graph.number_of_nodes() if self._backend == "networkx" else "?"
        n_edges = self._graph.number_of_edges() if self._backend == "networkx" else "?"
        logger.info(
            "populate_from_roadmap complete — %s nodes, %s edges, student='%s', domain='%s'",
            n_nodes, n_edges, self._student_id, domain,
        )

    def _add_edge_safe(self, src: str, dst: str) -> None:
        """Add a directed edge if both nodes exist and edge is not already present."""
        if self._backend == "networkx":
            if src in self._graph and dst in self._graph:
                if not self._graph.has_edge(src, dst):
                    self._graph.add_edge(src, dst)
        else:
            with self._driver.session() as session:
                session.run(
                    "MATCH (p:Concept {id: $src, student: $sid}), "
                    "      (c:Concept {id: $dst, student: $sid}) "
                    "MERGE (p)-[:PREREQUISITE_OF]->(c)",
                    src=src, dst=dst, sid=self._student_id,
                )

    # ------------------------------------------------------------------
    # Progress summary
    # ------------------------------------------------------------------

    def get_student_progress(self) -> Dict[str, Any]:
        """Return a summary of this student's progress across all domains."""
        if self._backend == "networkx":
            all_nodes = [(n, self._graph.nodes[n]) for n in self._graph.nodes]
        else:
            data      = self.get_graph_data()
            all_nodes = [(n["id"], n) for n in data["nodes"]]

        total       = len(all_nodes)
        mastered    = [n for n, d in all_nodes if d.get("mastery", 0.0) >= MASTERY_THRESHOLD]
        in_progress = [n for n, d in all_nodes if 0.0 < d.get("mastery", 0.0) < MASTERY_THRESHOLD]
        not_started = [n for n, d in all_nodes if d.get("mastery", 0.0) == 0.0]

        domain_acc: Dict[str, Dict] = {}
        for _, d in all_nodes:
            dom = d.get("domain", "unknown") or "unknown"
            if dom not in domain_acc:
                domain_acc[dom] = {"total": 0, "mastered": 0, "mastery_sum": 0.0}
            domain_acc[dom]["total"]       += 1
            domain_acc[dom]["mastery_sum"] += d.get("mastery", 0.0)
            if d.get("mastery", 0.0) >= MASTERY_THRESHOLD:
                domain_acc[dom]["mastered"] += 1

        domains = {
            dom: {
                "total":           v["total"],
                "mastered":        v["mastered"],
                "average_mastery": round(v["mastery_sum"] / v["total"], 3) if v["total"] else 0.0,
            }
            for dom, v in domain_acc.items()
        }

        sorted_nodes = sorted(all_nodes, key=lambda x: x[1].get("mastery", 0.0))
        weakest = [
            {"concept_id": n, "mastery": d.get("mastery", 0.0), "domain": d.get("domain", "")}
            for n, d in sorted_nodes[:3]
        ]
        strongest = [
            {"concept_id": n, "mastery": d.get("mastery", 0.0), "domain": d.get("domain", "")}
            for n, d in reversed(sorted_nodes[-3:])
        ]

        return {
            "total_concepts":     total,
            "mastered":           len(mastered),
            "in_progress":        len(in_progress),
            "not_started":        len(not_started),
            "domains":            domains,
            "weakest_concepts":   weakest,
            "strongest_concepts": strongest,
        }

    def get_graph_data_by_domain(self, domain: str) -> Dict[str, Any]:
        """Return nodes and edges filtered to a single domain (for per-course KG tabs)."""
        if self._backend == "networkx":
            nodes = [
                {
                    "id":         n,
                    "domain":     self._graph.nodes[n].get("domain", ""),
                    "mastery":    self._graph.nodes[n].get("mastery", 0.0),
                    "is_primary": self._graph.nodes[n].get("is_primary", False),
                    "module_id":  self._graph.nodes[n].get("module_id", ""),
                    "week":       self._graph.nodes[n].get("week", 0),
                }
                for n in self._graph.nodes
                if self._graph.nodes[n].get("domain", "") == domain
            ]
            node_ids = {nd["id"] for nd in nodes}
            edges = [
                {"source": u, "target": v}
                for u, v in self._graph.edges
                if u in node_ids and v in node_ids
            ]
        else:
            with self._driver.session() as session:
                node_result = session.run(
                    "MATCH (c:Concept {student: $sid, domain: $domain}) "
                    "RETURN c.id AS id, c.domain AS domain, c.mastery AS mastery, "
                    "       c.is_primary AS is_primary, c.module_id AS module_id, c.week AS week",
                    sid=self._student_id, domain=domain,
                )
                nodes = [
                    {
                        "id":         r["id"],
                        "domain":     r["domain"],
                        "mastery":    r["mastery"] or 0.0,
                        "is_primary": r["is_primary"] or False,
                        "module_id":  r["module_id"] or "",
                        "week":       r["week"] or 0,
                    }
                    for r in node_result
                ]
                edge_result = session.run(
                    "MATCH (p:Concept {student: $sid, domain: $domain})"
                    "-[:PREREQUISITE_OF]->(c:Concept {student: $sid, domain: $domain}) "
                    "RETURN p.id AS source, c.id AS target",
                    sid=self._student_id, domain=domain,
                )
                edges = [{"source": r["source"], "target": r["target"]} for r in edge_result]
        return {"nodes": nodes, "edges": edges}

    # ------------------------------------------------------------------
    # Rich Neo4j schema
    # ------------------------------------------------------------------

    def create_rich_schema(self, roadmap: Dict, student_name: str = "") -> None:
        """Create multi-label Neo4j graph: Student→Domain→Module→Concept.

        Only runs for Neo4j backend. Idempotent via MERGE — safe to call on
        every roadmap load. Never modifies existing Concept mastery scores.
        """
        if self._backend != "neo4j":
            return
        domain  = roadmap.get("domain", "")
        modules = roadmap.get("modules", [])
        name    = student_name or self._student_id

        with self._driver.session() as session:
            # 1. Student node
            session.run(
                "MERGE (s:Student {id: $sid}) SET s.name = $name",
                sid=self._student_id, name=name,
            )
            # 2. Domain node + STUDIES relationship
            session.run(
                "MERGE (d:Domain {name: $domain, student: $sid})",
                domain=domain, sid=self._student_id,
            )
            session.run(
                "MATCH (s:Student {id: $sid}), (d:Domain {name: $domain, student: $sid}) "
                "MERGE (s)-[:STUDIES]->(d)",
                sid=self._student_id, domain=domain,
            )
            # 3. Module nodes + HAS_MODULE relationships
            for mod in modules:
                mid = mod.get("module_id", "")
                session.run(
                    "MERGE (m:Module {id: $mid, student: $sid}) "
                    "SET m.title=$title, m.week=$week, m.difficulty=$diff, "
                    "    m.estimated_hours=$hours, m.domain=$domain",
                    mid=mid, sid=self._student_id,
                    title=mod.get("title", mid),
                    week=mod.get("week", 0),
                    diff=mod.get("difficulty", ""),
                    hours=mod.get("estimated_hours", 0),
                    domain=domain,
                )
                session.run(
                    "MATCH (d:Domain {name: $domain, student: $sid}), "
                    "      (m:Module {id: $mid, student: $sid}) "
                    "MERGE (d)-[:HAS_MODULE]->(m)",
                    domain=domain, sid=self._student_id, mid=mid,
                )
            # 4. LEADS_TO chain between modules ordered by week
            sorted_mods = sorted(modules, key=lambda x: x.get("week", 0))
            for i in range(len(sorted_mods) - 1):
                mid_a = sorted_mods[i].get("module_id", "")
                mid_b = sorted_mods[i + 1].get("module_id", "")
                session.run(
                    "MATCH (a:Module {id: $a, student: $sid}), "
                    "      (b:Module {id: $b, student: $sid}) "
                    "MERGE (a)-[:LEADS_TO]->(b)",
                    a=mid_a, b=mid_b, sid=self._student_id,
                )
            # 5. COVERS: Module → its Concept nodes
            for mod in modules:
                mid = mod.get("module_id", "")
                concept_ids = [
                    _normalize_concept(c).lower().replace(" ", "_")[:50]
                    for c in mod.get("concepts", [])
                ]
                for cid in concept_ids:
                    session.run(
                        "MATCH (m:Module {id: $mid, student: $sid}), "
                        "      (c:Concept {id: $cid, student: $sid}) "
                        "MERGE (m)-[:COVERS]->(c)",
                        mid=mid, cid=cid, sid=self._student_id,
                    )
        logger.info(
            "Rich schema created for student='%s' domain='%s' (%d modules)",
            self._student_id, domain, len(modules),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the Neo4j driver connection cleanly."""
        if self._backend == "neo4j" and hasattr(self, "_driver"):
            self._driver.close()

    def __del__(self) -> None:
        self.close()
