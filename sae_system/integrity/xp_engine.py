"""XP Engine: gamification layer — awards XP for learning milestones."""

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# XP awarded per event type
XP_TABLE: Dict[str, int] = {
    "concept_mastered": 100,
    "test_passed":      150,
    "perfect_score":    250,   # test score >= 95 %
    "domain_completed": 500,
    "daily_streak":      50,   # multiplied by min(streak_days, 7)
}

# Ordered list of (min_xp, level_name)
LEVELS: List[Tuple[int, str]] = [
    (0,      "Novice"),
    (500,    "Learner"),
    (1_500,  "Student"),
    (3_000,  "Scholar"),
    (6_000,  "Expert"),
    (10_000, "Master"),
    (20_000, "Sovereign"),
]


class XPEngine:
    """Tracks XP, level, and daily streak for one student."""

    def __init__(self, student_id: str) -> None:
        self._student_id = student_id
        self._path = _DATA_DIR / f"{student_id}_xp.json"
        self._data = self._load()

    # ------------------------------------------------------------------ I/O

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"total_xp": 0, "streak_days": 0, "last_activity": None, "events": []}

    def _save(self) -> None:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------ Core

    def award(self, event: str, metadata: Optional[Dict] = None) -> int:
        """Award XP for a named event and return the total XP credited.

        Streak bonus is added for concept_mastered, test_passed, and
        domain_completed events on consecutive calendar days (capped at 7×).

        Args:
            event: Key from XP_TABLE (e.g. "concept_mastered").
            metadata: Optional dict of extra fields stored in the event log.

        Returns:
            Total XP credited (base + streak bonus). 0 if event unknown.
        """
        base_xp = XP_TABLE.get(event, 0)
        if base_xp == 0:
            return 0

        today  = date.today().isoformat()
        last   = self._data.get("last_activity")
        streak = self._data.get("streak_days", 0)

        if last is None:
            streak = 1
        elif last == today:
            pass  # already active today — don't increment streak
        else:
            delta = (date.today() - date.fromisoformat(last)).days
            streak = (streak + 1) if delta == 1 else 1

        streak_bonus = 0
        if event in ("concept_mastered", "test_passed", "domain_completed"):
            streak_bonus = XP_TABLE["daily_streak"] * min(streak, 7)

        awarded = base_xp + streak_bonus
        self._data["total_xp"]      = self._data.get("total_xp", 0) + awarded
        self._data["streak_days"]   = streak
        self._data["last_activity"] = today
        self._data.setdefault("events", []).append({
            "event":      event,
            "xp":         awarded,
            "streak_day": streak,
            "ts":         datetime.now(timezone.utc).isoformat(),
            **(metadata or {}),
        })
        self._save()
        return awarded

    # ------------------------------------------------------------------ Queries

    def total_xp(self) -> int:
        """Return the student's accumulated XP."""
        return self._data.get("total_xp", 0)

    def streak(self) -> int:
        """Return the current consecutive-day streak."""
        return self._data.get("streak_days", 0)

    def level(self) -> Tuple[str, int, int]:
        """Return (level_name, total_xp, xp_to_next_level).

        xp_to_next_level is 0 when the student has reached the maximum level.
        """
        xp = self.total_xp()
        current_name = LEVELS[0][1]
        for threshold, name in LEVELS:
            if xp >= threshold:
                current_name = name
        for i, (threshold, _) in enumerate(LEVELS):
            if xp < threshold:
                return current_name, xp, threshold - xp
        return current_name, xp, 0  # max level reached

    def recent_events(self, n: int = 10) -> List[Dict]:
        """Return the n most recent XP award events."""
        return self._data.get("events", [])[-n:]

    def summary(self) -> Dict:
        """Return a summary dict suitable for display in the dashboard."""
        level_name, xp, xp_to_next = self.level()
        return {
            "total_xp":    xp,
            "level":       level_name,
            "xp_to_next":  xp_to_next,
            "streak":      self.streak(),
            "events_count": len(self._data.get("events", [])),
        }
