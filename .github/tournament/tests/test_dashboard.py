from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

from hkpug_challenge.leaderboard import PublicLeaderboard


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
LEADERBOARD = DASHBOARD / "leaderboard"
START = DASHBOARD / "start"
OPIK = DASHBOARD / "opik"


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


def parse_page(path: Path) -> tuple[str, DashboardParser]:
    html = path.read_text(encoding="utf-8")
    parser = DashboardParser()
    parser.feed(html)
    return html, parser


def test_root_page_is_a_participant_focused_challenge_overview() -> None:
    html, parser = parse_page(DASHBOARD / "index.html")

    assert parser.h1_count == 1
    assert parser.has_skip_link
    assert {"header", "main", "section", "nav", "footer"} <= set(parser.tags)
    assert "Improve one prompt. Learn from every run." in html
    for background in (
        "HarbourCloud's support copilot",
        "Fifty cases across ten support domains",
        "DeepSeek V4 Flash",
        "The shared handbook and one domain evidence pack",
        "A single system prompt",
    ):
        assert background in html
    assert 'href="start/"' in html
    assert 'href="tutorial/"' in html
    assert 'href="submission-feedback/"' in html
    assert 'href="leaderboard/"' in html
    for noise in (
        "Public data",
        "Answer contract",
        "common tournament harness",
        "trusted workflow",
        "team_private_key.pem",
    ):
        assert noise not in html


def test_first_submission_tutorial_is_complete_and_cross_platform() -> None:
    html, parser = parse_page(START / "index.html")

    assert parser.h1_count == 1
    assert parser.has_skip_link
    assert {"header", "main", "section", "nav", "footer"} <= set(parser.tags)
    for text in (
        "First submission",
        "macOS",
        "Linux",
        "Windows",
        "hkpug-opik-helper doctor",
        "hkpug-opik-helper pack",
        "hkpug-opik-helper inspect",
        "submission/submission.zip",
        "git add submission/submission.zip",
        "does not use an attempt",
    ):
        assert text in html
    assert "releases/latest" in html
    assert "encrypt_prompt.sh" not in html
    assert "openssl" not in html.lower()
    assert "uv run" not in html


def test_opik_tutorial_uses_only_public_helper_commands() -> None:
    html, parser = parse_page(OPIK / "index.html")

    assert parser.h1_count == 1
    assert parser.has_skip_link
    assert {"header", "main", "section", "nav", "footer"} <= set(parser.tags)
    for text in (
        "Inspect feedback in Opik",
        "Start Opik locally",
        "./opik.sh",
        "hkpug-opik-helper decrypt",
        "hkpug-opik-helper load",
        "http://localhost:5173",
    ):
        assert text in html
    for noise in (
        ".github/tournament",
        "import_opik.py",
        "uv run",
        "HKPUG Mini Workshop",
        "group-00.opik-workshop.python.hk",
    ):
        assert noise not in html


def test_leaderboard_has_semantic_structure_and_required_states() -> None:
    html, parser = parse_page(LEADERBOARD / "index.html")

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
    assert "../styles.css" in parser.links
    assert "app.js" in parser.scripts
    assert "No scored attempts yet" in html
    assert "could not be loaded" in html


def test_leaderboard_script_uses_public_json_and_safe_dom_updates() -> None:
    script = (LEADERBOARD / "app.js").read_text(encoding="utf-8")

    assert 'fetch("leaderboard.json"' in script
    assert "textContent" in script
    assert "innerHTML" not in script
    assert "renderRunTrend" in script
    assert "renderCriterionBreakdown" in script


def test_dashboard_styles_include_responsive_and_focus_treatment() -> None:
    styles = (DASHBOARD / "styles.css").read_text(encoding="utf-8")

    assert "@media (max-width: 720px)" in styles
    assert ":focus-visible" in styles
    assert "prefers-reduced-motion" in styles
    assert "letter-spacing: 0" in styles


def test_seed_leaderboard_is_valid_public_empty_state() -> None:
    payload = json.loads((LEADERBOARD / "leaderboard.json").read_text(encoding="utf-8"))
    leaderboard = PublicLeaderboard.model_validate(payload)

    assert leaderboard.schema_version == 1
    assert leaderboard.challenge.max_attempts == 8
    assert leaderboard.challenge.weights.discovery == 0.75
    assert leaderboard.challenge.weights.holdout == 0.25
    assert leaderboard.teams == ()
