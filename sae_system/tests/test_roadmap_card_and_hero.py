"""Roadmap card rendering (raw <div> text shown as a code block) and removal of the
"Your Study Buddies" expander.

Root cause of the card bug: the card was a triple-quoted template with {res_html} on
its own line. A module with no resource link left a whitespace-only line, which ends
Markdown's HTML block; the indented {mastery_html} below it then rendered as a code
block. The card is now one newline-free string, so that cannot happen.
Runs the real app.py through AppTest in a temp cwd, so nothing in the repo's data/ changes.
"""

import pytest
from streamlit.testing.v1 import AppTest

import evaluation.event_log as event_log
from pathlib import Path

APP = str(Path(__file__).resolve().parent.parent / "dashboard" / "app.py")

ROADMAP = {
    "domain": "Digital Marketing",
    "total_weeks": 10,
    "modules": [
        {   # no resources -> the exact condition from the screenshot
            "week": 1, "module_id": "introduction_to_digital_marketing",
            "title": "Introduction to Digital Marketing",
            "description": "This module introduces the fundamental concepts of digital marketing, including its "
                           "history, key players, and current trends. It covers the basics of digital marketing "
                           "channels and how they fit together in a modern strategy for businesses of every size.",
            "concepts": ["Digital Marketing Overview", "History of Digital Marketing", "Key Players"],
            "prerequisites": [], "estimated_hours": 5, "difficulty": "Beginner", "resources": [],
        },
        {   # has a resource, and hostile characters in LLM-written text
            "week": 2, "module_id": "seo_basics", "title": "SEO <b>& Basics</b>",
            "description": "Rank with <script>alert(1)</script> keywords & links.",
            "concepts": ["On-page <i>SEO</i>", "Backlinks"],
            "prerequisites": ["introduction_to_digital_marketing"], "estimated_hours": 6,
            "difficulty": "Beginner",
            "resources": [{"title": "SEO <x>", "summary": "s", "url": "https://example.org/a?b=1&c=\"2\""}],
        },
    ],
}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                                   # KnowledgeGraph uses ./data relative to cwd
    monkeypatch.setattr(event_log, "_LOG_PATH", tmp_path / "events.jsonl")
    monkeypatch.setattr(event_log, "_DATA_DIR", tmp_path)

    def make(page, **state):
        at = AppTest.from_file(APP, default_timeout=240)
        base = dict(student_id="card-test", student_name="Card Test", domain="Digital Marketing",
                    roadmap=ROADMAP, modules_unlocked={ROADMAP["modules"][0]["module_id"]}, page=page)
        for k, v in {**base, **state}.items():
            at.session_state[k] = v
        return at.run()
    return make


def card_blocks(at):
    return [m.value for m in at.markdown if 'class="sae-card"' in m.value and "Week " in m.value]


def test_roadmap_page_renders_without_error(app):
    at = app("roadmap")
    assert not at.exception, [str(e.value) for e in at.exception]


def test_every_card_is_one_newline_free_block_so_it_cannot_become_a_code_block(app):
    cards = card_blocks(app("roadmap"))
    assert len(cards) == 2
    for c in cards:
        assert "\n" not in c, "a newline lets Markdown end the HTML block / start an indented code block"
        assert c.startswith('<div class="sae-card"') and c.endswith("</div>")


def test_module_without_resources_still_renders_its_mastery_bar_inside_the_card(app):
    first = card_blocks(app("roadmap"))[0]
    assert "Mastery" in first and "Not started" in first          # the part that leaked as raw <div> text
    assert "📚" not in first                                       # no resource link for this module


def test_llm_text_is_escaped_so_it_cannot_inject_markup(app):
    second = card_blocks(app("roadmap"))[1]
    assert "<script>" not in second and "&lt;script&gt;" in second
    assert "<b>" not in second and "&lt;b&gt;" in second
    assert "&amp; Basics" in second
    assert 'href="https://example.org/a?b=1&amp;c=&quot;2&quot;"' in second   # attribute-safe URL


def test_description_is_clamped_to_three_lines_for_consistent_card_height(app):
    assert "-webkit-line-clamp:3" in card_blocks(app("roadmap"))[0]


def test_roadmap_card_has_no_stray_code_block_elements(app):
    at = app("roadmap")
    assert len(at.code) == 0


# ---------------------------------------------------------------- Study Buddies removed

@pytest.mark.parametrize("page", ["roadmap", "home", "knowledge_graph"])
def test_no_study_buddies_expander_on_main_pages(app, page):
    at = app(page)
    assert not at.exception, [str(e.value) for e in at.exception]
    assert not [e for e in at.expander if "Study Buddies" in e.label]


def test_no_study_buddies_expander_on_lesson_page(app):
    lesson = {k: "text " * 12 for k in ("introduction", "theory", "example", "misconceptions", "applications", "summary")}
    lesson.update(concept_id="Digital Marketing Overview", domain="Digital Marketing")
    at = app("lesson", lesson=lesson, lesson_section=0, current_module_idx=0, current_concept_idx=0)
    assert not at.exception, [str(e.value) for e in at.exception]
    assert not [e for e in at.expander if "Study Buddies" in e.label]


def test_hero_helper_is_gone_from_the_app_source():
    src = Path(APP).read_text(encoding="utf-8")
    assert "render_hero_scene" not in src and "Your Study Buddies" not in src
