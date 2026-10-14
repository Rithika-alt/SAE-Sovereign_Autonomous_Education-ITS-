"""Enrolment persistence: Home said "You haven't started a learning domain yet" for a
student who had chosen Digital Marketing, generated its roadmap and had a populated
knowledge graph — because "enrolled" means "has a saved progress record" and that
record was only written on Log Out or after passing a test.

Everything runs in a temp dir (graphs, progress, roadmaps, event log): nothing in the
repo's data/ is read or written.
"""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import evaluation.event_log as event_log
import evaluation.recommendation_engine as rec_engine
import persistence.progress_store as ps
from memory.graph_engine import KnowledgeGraph

APP = str(Path(__file__).resolve().parent.parent / "dashboard" / "app.py")
SID = "teena-test"
DOMAIN = "Digital Marketing"
M1, M2 = "introduction_to_digital_marketing", "seo_basics"

ROADMAP = {
    "domain": DOMAIN, "total_weeks": 10,
    "modules": [
        {"week": 1, "module_id": M1, "title": "Introduction to Digital Marketing", "description": "d",
         "concepts": ["Digital Marketing Overview", "History of Digital Marketing"], "prerequisites": [],
         "estimated_hours": 5, "difficulty": "Beginner", "resources": []},
        {"week": 2, "module_id": M2, "title": "SEO Basics", "description": "d",
         "concepts": ["On-page SEO", "Backlinks"], "prerequisites": [M1],
         "estimated_hours": 5, "difficulty": "Beginner", "resources": []},
    ],
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                                         # KnowledgeGraph writes ./data/...
    monkeypatch.setattr(event_log, "_LOG_PATH", tmp_path / "events.jsonl")
    monkeypatch.setattr(event_log, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(ps, "_DIR", tmp_path / "progress")
    roadmaps = tmp_path / "roadmaps"
    roadmaps.mkdir()
    (roadmaps / "digital_marketing.json").write_text(json.dumps(ROADMAP), encoding="utf-8")
    monkeypatch.setattr(rec_engine, "_ROADMAP_DIR", roadmaps)
    return tmp_path


def teena_state():
    """Exactly what was on disk for Teena: a populated graph, no progress file."""
    KnowledgeGraph(student_id=SID).populate_from_roadmap(ROADMAP)


def record():
    p = ps._path(SID)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def home(**state):
    at = AppTest.from_file(APP, default_timeout=240)
    base = dict(student_id=SID, student_name="Teena V", page="home")
    for k, v in {**base, **state}.items():
        at.session_state[k] = v
    return at.run()


def card_text(at):
    return " ".join(m.value for m in at.markdown)


# ---------------------------------------------------------------- progress_store.ensure_enrolled

def test_ensure_enrolled_creates_a_record_and_enrols_the_domain(env):
    assert ps.get_enrolled_domains(SID) == []
    assert ps.ensure_enrolled(SID, DOMAIN, modules_unlocked={M1}) is True
    assert ps.get_enrolled_domains(SID) == [DOMAIN] and ps.get_last_domain(SID) == DOMAIN
    assert ps.load_progress(SID, DOMAIN)["modules_unlocked"] == {M1}


def test_ensure_enrolled_never_overwrites_existing_progress(env):
    ps.save_progress(SID, DOMAIN, {M1}, {M1, M2}, {M1: 100.0})
    assert ps.ensure_enrolled(SID, DOMAIN, modules_unlocked=set()) is False
    saved = ps.load_progress(SID, DOMAIN)
    assert saved["modules_passed"] == {M1} and saved["modules_unlocked"] == {M1, M2}


def test_ensure_enrolled_ignores_blank_ids(env):
    assert ps.ensure_enrolled("", DOMAIN) is False and ps.ensure_enrolled(SID, "") is False
    assert not ps._path(SID).exists()


# ---------------------------------------------------------------- the recommendation engine

def test_teenas_state_reproduces_get_started_then_recommends_week_1_once_enrolled(env):
    teena_state()
    before = rec_engine.recommend_next_actions(SID)
    assert [r["action"] for r in before] == ["start_domain"]            # the bug, reproduced

    ps.ensure_enrolled(SID, DOMAIN, modules_unlocked={M1})
    after = rec_engine.recommend_next_actions(SID)
    assert after[0]["action"] == "continue" and after[0]["concept_id"] == M1 and after[0]["domain"] == DOMAIN
    assert "unlocked and ready" in after[0]["reason"]


# ---------------------------------------------------------------- Home repairs an already-broken session

def test_home_repairs_a_session_that_has_a_domain_but_no_saved_record(env):
    teena_state()
    assert record() is None
    at = home(domain=DOMAIN, roadmap=ROADMAP)                            # Teena's session: no modules_unlocked saved
    assert not at.exception, [str(e.value) for e in at.exception]
    assert record()["domains"][DOMAIN]["modules_unlocked"] == [M1]       # first module unlocked, like loading_roadmap does
    assert record()["last_domain"] == DOMAIN
    assert "You haven't started a learning domain yet" not in card_text(at)
    labels = [b.label for b in at.button]
    assert f"Continue {DOMAIN}" in labels and "Choose a domain" not in labels


def test_home_repair_does_not_touch_an_existing_record(env):
    teena_state()
    ps.save_progress(SID, DOMAIN, {M1}, {M1, M2}, {M1: 100.0})
    before = record()
    at = home(domain=DOMAIN, roadmap=ROADMAP, modules_passed={M1}, modules_unlocked={M1, M2})
    assert not at.exception, [str(e.value) for e in at.exception]
    assert record() == before


def test_a_genuinely_new_student_still_sees_get_started_and_gets_no_record(env):
    at = home()                                                          # no domain chosen yet
    assert not at.exception, [str(e.value) for e in at.exception]
    assert record() is None
    assert "Choose a domain" in [b.label for b in at.button]


# ---------------------------------------------------------------- enrolment saved when the roadmap loads

def test_loading_the_roadmap_saves_enrolment_without_logout_or_a_test(env, monkeypatch):
    from agents.roadmap_agent import RoadmapAgent
    monkeypatch.setattr(RoadmapAgent, "generate_roadmap",
                        lambda self, domain, progress_callback=None, student_id="default": ROADMAP)
    assert record() is None
    at = AppTest.from_file(APP, default_timeout=240)
    for k, v in dict(student_id=SID, student_name="Teena V", domain=DOMAIN, page="loading_roadmap").items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert at.session_state["page"] == "roadmap"
    assert ps.get_enrolled_domains(SID) == [DOMAIN]
    assert ps.load_progress(SID, DOMAIN)["modules_unlocked"] == {M1}
    assert ps.get_last_domain(SID) == DOMAIN


def test_reloading_the_roadmap_keeps_previously_saved_progress(env, monkeypatch):
    from agents.roadmap_agent import RoadmapAgent
    monkeypatch.setattr(RoadmapAgent, "generate_roadmap",
                        lambda self, domain, progress_callback=None, student_id="default": ROADMAP)
    ps.save_progress(SID, DOMAIN, {M1}, {M1, M2}, {M1: 100.0})
    saved = ps.load_progress(SID, DOMAIN)                                # the session is seeded from it, as at domain selection
    at = AppTest.from_file(APP, default_timeout=240)
    for k, v in dict(student_id=SID, student_name="Teena V", domain=DOMAIN, page="loading_roadmap",
                     modules_passed=saved["modules_passed"], modules_unlocked=saved["modules_unlocked"],
                     module_progress=saved["module_progress"]).items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    after = ps.load_progress(SID, DOMAIN)
    assert after["modules_passed"] == {M1} and after["modules_unlocked"] == {M1, M2}
    assert after["module_progress"] == {M1: 100.0}
