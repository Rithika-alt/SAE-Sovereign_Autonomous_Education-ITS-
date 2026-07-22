"""Per-student, per-domain progress store backed by a JSON file.

Stores modules_passed, modules_unlocked, module_progress keyed by student_id
and domain so progress survives logout/login cycles. Falls back gracefully
(returns empty sets/dicts) when the file does not exist or cannot be read.
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Set

logger = logging.getLogger(__name__)

_DIR = Path(__file__).resolve().parent.parent / "data" / "progress"


def _path(student_id: str) -> Path:
    _DIR.mkdir(parents=True, exist_ok=True)
    return _DIR / f"{student_id}.json"


def _load_raw(student_id: str) -> dict:
    p = _path(student_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"student_id": student_id, "last_domain": "", "domains": {}}


def load_progress(student_id: str, domain: str) -> Dict:
    """Return restored progress for one student + domain.

    Always returns a dict with keys:
      modules_passed   → set[str]
      modules_unlocked → set[str]
      module_progress  → dict[str, float]
      last_domain      → str
    """
    data = _load_raw(student_id)
    d = data.get("domains", {}).get(domain, {})
    return {
        "modules_passed":   set(d.get("modules_passed",   [])),
        "modules_unlocked": set(d.get("modules_unlocked", [])),
        "module_progress":  dict(d.get("module_progress",  {})),
        "last_domain":      data.get("last_domain", ""),
    }


def save_progress(
    student_id: str,
    domain: str,
    modules_passed: Set[str],
    modules_unlocked: Set[str],
    module_progress: Dict[str, float],
) -> None:
    """Persist current progress for one student + domain (silent on failure)."""
    if not student_id or not domain:
        return
    try:
        data = _load_raw(student_id)
        data["last_domain"] = domain
        data["domains"][domain] = {
            "modules_passed":   sorted(modules_passed),
            "modules_unlocked": sorted(modules_unlocked),
            "module_progress":  {k: float(v) for k, v in module_progress.items()},
        }
        _path(student_id).write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.debug("Progress saved for student=%s domain=%s", student_id, domain)
    except Exception as exc:
        logger.warning("save_progress failed for %s: %s", student_id, exc)


def get_enrolled_domains(student_id: str) -> List[str]:
    """Return all domains the student has any saved progress in."""
    return list(_load_raw(student_id).get("domains", {}).keys())
