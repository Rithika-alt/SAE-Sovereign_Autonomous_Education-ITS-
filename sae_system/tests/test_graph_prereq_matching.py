"""populate_from_roadmap: prerequisite references must match module ids after the
same normalization used for concept names (lowercase, spaces -> underscores).

Before the fix an LLM-written prerequisite such as "Supervised Learning" never
matched module_id "supervised_learning", and the edge was dropped silently.
Tests run in a temp cwd so data/knowledge_graphs/ in the repo is never touched.
"""

import glob
import json
import logging
from pathlib import Path

import pytest

from memory.graph_engine import KnowledgeGraph, _concept_key

LOGGER = "memory.graph_engine"
ROADMAP_DIR = Path(__file__).resolve().parent.parent / "data" / "roadmaps"


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def mod(mid, concepts, prereqs=(), week=1):
    return {"module_id": mid, "week": week, "title": mid, "concepts": list(concepts),
            "prerequisites": list(prereqs)}


def roadmap(*modules):
    return {"domain": "Machine Learning", "modules": list(modules)}


def build(rm, student="t"):
    g = KnowledgeGraph(student_id=student)
    g.populate_from_roadmap(rm)
    return g


def edges(g):
    return set(g._graph.edges)


def three_modules(prereq):
    # supervised_learning is NOT the module right before deep_learning, so the
    # only way to get sup_two -> deep_one is Rule 3 (the prerequisites list).
    return roadmap(
        mod("supervised_learning", ["Sup One", "Sup Two"], week=1),
        mod("other_topic", ["Other One"], week=2),
        mod("deep_learning", ["Deep One"], prereqs=[prereq], week=3),
    )


# ---------------------------------------------------------------- the fix

def test_title_form_prerequisite_creates_the_edge():
    g = build(three_modules("Supervised Learning"))
    assert ("sup_two", "deep_one") in edges(g)


@pytest.mark.parametrize("written", ["Supervised Learning", "SUPERVISED LEARNING", "supervised learning",
                                     "Supervised_Learning"])
def test_case_and_space_variants_resolve(written):
    assert ("sup_two", "deep_one") in edges(build(three_modules(written)))


def test_exact_module_id_still_resolves():
    assert ("sup_two", "deep_one") in edges(build(three_modules("supervised_learning")))


def test_unresolvable_prerequisite_is_skipped_and_logged_not_raised(caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER):
        g = build(three_modules("Linear Algebra"))
    assert ("sup_two", "deep_one") not in edges(g)
    # the rest of the graph is still built (Rules 1 and 2)
    assert ("sup_one", "sup_two") in edges(g) and ("sup_two", "other_one") in edges(g)
    msgs = [r.getMessage() for r in caplog.records if r.name == LOGGER]
    assert any("'Linear Algebra'" in m and "'deep_learning'" in m for m in msgs), msgs
    assert all(r.levelno == logging.INFO for r in caplog.records if "Linear Algebra" in r.getMessage())


def test_resolved_prerequisite_is_not_logged_as_unresolved(caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER):
        build(three_modules("Supervised Learning"))
    assert not [r for r in caplog.records if "no edge created" in r.getMessage()]


def test_prerequisite_naming_a_module_with_no_concepts_is_logged(caplog):
    rm = roadmap(
        mod("empty_module", [], week=1),
        mod("next_module", ["N One"], prereqs=["Empty Module"], week=2),
    )
    with caplog.at_level(logging.INFO, logger=LOGGER):
        g = build(rm)
    assert [r for r in caplog.records if "'Empty Module'" in r.getMessage()]
    assert edges(g) == set()


def test_non_string_prerequisites_do_not_crash(caplog):
    rm = roadmap(
        mod("supervised_learning", ["Sup One"], week=1),
        mod("other_topic", ["Other One"], week=2),
        mod("deep_learning", ["Deep One"], prereqs=[None, {"name": "Supervised Learning"}, 42], week=3),
    )
    with caplog.at_level(logging.INFO, logger=LOGGER):
        g = build(rm)
    assert ("sup_one", "deep_one") in edges(g)           # the dict form resolved via _normalize_concept
    unresolved = [r.getMessage() for r in caplog.records if "no edge created" in r.getMessage()]
    assert len(unresolved) == 2                          # None and 42


def test_exact_id_wins_over_a_normalised_duplicate():
    # "A B" and "a_b" normalise to the same key; an exact reference must hit its own module.
    rm = roadmap(
        mod("a_b", ["First Concept"], week=1),
        mod("A B", ["Second Concept"], week=2),
        mod("target", ["Target One"], prereqs=["A B"], week=3),
    )
    g = build(rm)
    assert ("second_concept", "target_one") in edges(g)
    assert ("first_concept", "target_one") not in edges(g)


def test_prerequisite_written_as_a_long_title_matches_the_30_char_truncated_module_id():
    # RoadmapAgent cuts module ids to 30 chars: "Introduction to Digital Marketing" (33) ->
    # "introduction_to_digital_market". A prerequisite written as the full title must still resolve.
    long_id = "introduction_to_digital_market"
    rm = roadmap(
        mod(long_id, ["Overview", "History"], week=1),
        mod("other_topic", ["Other One"], week=2),
        mod("core_concepts", ["Core One"], prereqs=["Introduction to Digital Marketing"], week=3),
    )
    assert ("history", "core_one") in edges(build(rm))


def test_prefix_match_does_not_resolve_unrelated_prerequisites(caplog):
    rm = roadmap(
        mod("introduction_to_digital_market", ["Overview"], week=1),
        mod("other_topic", ["Other One"], week=2),
        mod("core_concepts", ["Core One"], prereqs=["Introduction to Cooking Basics Today"], week=3),
    )
    with caplog.at_level(logging.INFO, logger=LOGGER):
        g = build(rm)
    assert ("overview", "core_one") not in edges(g)
    assert [r for r in caplog.records if "Introduction to Cooking" in r.getMessage()]


# ---------------------------------------------------------------- what must NOT change

def test_node_creation_is_identical_with_and_without_prerequisites():
    with_prereqs = build(three_modules("Supervised Learning"), student="a")
    without = build(roadmap(*[{**m, "prerequisites": []} for m in three_modules("x")["modules"]]), student="b")
    assert dict(with_prereqs._graph.nodes(data=True)) == dict(without._graph.nodes(data=True))
    assert with_prereqs._graph.nodes["sup_one"]["is_primary"] is True
    assert with_prereqs._graph.nodes["deep_one"]["week"] == 3


def test_concept_ids_use_the_same_rule_as_before():
    assert _concept_key("Neural Networks") == "neural_networks"
    assert _concept_key({"concept": "API Design"}) == "api_design"
    assert _concept_key("x" * 80) == "x" * 50


def test_populate_is_idempotent_and_keeps_mastery():
    rm = three_modules("Supervised Learning")
    g = build(rm)
    g.update_mastery("sup_one", 0.7)
    nodes_before, edges_before = dict(g._graph.nodes(data=True)), edges(g)
    g.populate_from_roadmap(rm)
    assert edges(g) == edges_before
    assert g._graph.nodes["sup_one"]["mastery"] == 0.7
    assert {k: v for k, v in g._graph.nodes(data=True)} == nodes_before


def test_a_prerequisite_that_is_already_the_previous_module_adds_no_duplicate_edge():
    rm = roadmap(
        mod("supervised_learning", ["Sup One"], week=1),
        mod("deep_learning", ["Deep One"], prereqs=["Supervised Learning"], week=2),
    )
    g = build(rm)
    assert g._graph.number_of_edges() == 1               # Rule 2 edge; Rule 3 de-duplicated


# ---------------------------------------------------------------- real roadmaps

@pytest.mark.parametrize("path", sorted(glob.glob(str(ROADMAP_DIR / "*.json"))), ids=lambda p: Path(p).stem)
def test_every_normalisable_prerequisite_in_real_roadmaps_has_its_edge(path):
    rm = json.loads(Path(path).read_text(encoding="utf-8"))
    g = build(rm)
    concepts = {m["module_id"]: [_concept_key(c) for c in m.get("concepts", [])] for m in rm["modules"]}
    by_key = {}
    for mid in concepts:
        by_key.setdefault(_concept_key(mid), mid)
    checked = 0
    for m in rm["modules"]:
        for p in m.get("prerequisites", []):
            target = p if p in concepts else by_key.get(_concept_key(p))
            if target and concepts[target] and concepts[m["module_id"]]:
                checked += 1
                assert g._graph.has_edge(concepts[target][-1], concepts[m["module_id"]][0]), \
                    f"{Path(path).stem}: {p!r} -> {m['module_id']!r}"
    assert checked > 0
