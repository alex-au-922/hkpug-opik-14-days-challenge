from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

from hkpug_challenge.leaderboard import PublicLeaderboard


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"


class DashboardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.ids: set[str] = set()
        self.links: list[str] = []
        self.scripts: list[str] = []
        self.h1_count = 0
        self.has_skip_link = False
        self.has_live_region = False
        self.has_alert = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        self.tags.append(tag)
        if value := values.get("id"):
            self.ids.add(value)
        if tag == "h1":
            self.h1_count += 1
        if tag == "a" and values.get("href") == "#main-content":
            self.has_skip_link = True
        if values.get("aria-live"):
            self.has_live_region = True
        if values.get("role") == "alert":
            self.has_alert = True
        if tag == "link" and (href := values.get("href")):
            self.links.append(href)
        if tag == "script" and (src := values.get("src")):
            self.scripts.append(src)


def test_dashboard_has_semantic_structure_and_required_states() -> None:
    html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
    parser = DashboardParser()
    parser.feed(html)

    assert parser.h1_count == 1
    assert parser.has_skip_link
    assert parser.has_live_region
    assert parser.has_alert
    assert {"header", "main", "section", "table", "caption", "thead", "tbody"} <= set(
        parser.tags
    )
    assert {
        "main-content",
        "challenge-status",
        "challenge-dates",
        "leaderboard-body",
        "loading-state",
        "empty-state",
        "error-state",
        "team-detail",
        "run-trend",
        "criterion-breakdown",
    } <= parser.ids
    assert "styles.css" in parser.links
    assert "app.js" in parser.scripts
    assert 'rel="icon" href="data:,"' in html


def test_dashboard_script_uses_public_json_and_safe_dom_updates() -> None:
    script = (DASHBOARD / "app.js").read_text(encoding="utf-8")

    assert 'fetch("leaderboard.json"' in script
    assert "textContent" in script
    assert "innerHTML" not in script
    assert "No scored attempts yet" in (DASHBOARD / "index.html").read_text(
        encoding="utf-8"
    )
    assert "could not be loaded" in (DASHBOARD / "index.html").read_text(
        encoding="utf-8"
    )
    assert "renderRunTrend" in script
    assert "renderCriterionBreakdown" in script


def test_dashboard_styles_include_responsive_and_focus_treatment() -> None:
    styles = (DASHBOARD / "styles.css").read_text(encoding="utf-8")

    assert "@media (max-width: 720px)" in styles
    assert ":focus-visible" in styles
    assert "prefers-reduced-motion" in styles
    assert "letter-spacing: 0" in styles


def test_seed_leaderboard_is_valid_public_empty_state() -> None:
    path = DASHBOARD / "leaderboard.json"
    raw = path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    leaderboard = PublicLeaderboard.model_validate(payload)

    assert leaderboard.schema_version == 1
    assert leaderboard.challenge.max_attempts == 8
    assert leaderboard.challenge.weights.discovery == 0.75
    assert leaderboard.challenge.weights.holdout == 0.25
    assert leaderboard.teams == ()
