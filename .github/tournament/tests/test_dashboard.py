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
TUTORIAL = DASHBOARD / "tutorial"
SUBMISSION_FEEDBACK = DASHBOARD / "submission-feedback"


class DashboardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.ids: set[str] = set()
        self.anchors: list[dict[str, str | None]] = []
        self.links: list[str] = []
        self.scripts: list[str] = []
        self.site_nav_links: list[tuple[str, str | None, str | None]] = []
        self.h1_count = 0
        self.has_skip_link = False
        self.has_live_region = False
        self.has_alert = False
        self._in_site_nav = False
        self._site_nav_anchor: dict[str, str | None] | None = None
        self._site_nav_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        self.tags.append(tag)
        if value := values.get("id"):
            self.ids.add(value)
        if tag == "h1":
            self.h1_count += 1
        if tag == "nav" and values.get("class") == "site-nav":
            self._in_site_nav = True
        if tag == "a":
            self.anchors.append(values)
            if self._in_site_nav:
                self._site_nav_anchor = values
                self._site_nav_text = []
            if values.get("href") == "#main-content":
                self.has_skip_link = True
        if values.get("aria-live"):
            self.has_live_region = True
        if values.get("role") == "alert":
            self.has_alert = True
        if tag == "link" and (href := values.get("href")):
            self.links.append(href)
        if tag == "script" and (src := values.get("src")):
            self.scripts.append(src)

    def handle_data(self, data: str) -> None:
        if self._site_nav_anchor is not None:
            self._site_nav_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._site_nav_anchor is not None:
            label = " ".join("".join(self._site_nav_text).split())
            self.site_nav_links.append(
                (
                    label,
                    self._site_nav_anchor.get("href"),
                    self._site_nav_anchor.get("aria-current"),
                )
            )
            self._site_nav_anchor = None
            self._site_nav_text = []
        if tag == "nav" and self._in_site_nav:
            self._in_site_nav = False


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
    assert 'href="start/"' in html
    assert 'href="tutorial/"' in html
    assert 'href="leaderboard/"' in html
    assert "Eight total" in html
    assert "Eight maximum" in html
    assert "Four maximum" not in html
    for noise in (
        "Public data",
        "Answer contract",
        "common tournament harness",
        "trusted workflow",
        "team_private_key.pem",
    ):
        assert noise not in html


def test_participant_navigation_is_identical_and_marks_current_page() -> None:
    pages = {
        DASHBOARD / "index.html": (
            ("Overview", "./", "page"),
            ("Tutorial", "tutorial/", None),
            ("First submission", "start/", None),
            ("Submission feedback", "submission-feedback/", None),
            ("Leaderboard", "leaderboard/", None),
        ),
        TUTORIAL / "index.html": (
            ("Overview", "../", None),
            ("Tutorial", "./", "page"),
            ("First submission", "../start/", None),
            ("Submission feedback", "../submission-feedback/", None),
            ("Leaderboard", "../leaderboard/", None),
        ),
        START / "index.html": (
            ("Overview", "../", None),
            ("Tutorial", "../tutorial/", None),
            ("First submission", "./", "page"),
            ("Submission feedback", "../submission-feedback/", None),
            ("Leaderboard", "../leaderboard/", None),
        ),
        SUBMISSION_FEEDBACK / "index.html": (
            ("Overview", "../", None),
            ("Tutorial", "../tutorial/", None),
            ("First submission", "../start/", None),
            ("Submission feedback", "./", "page"),
            ("Leaderboard", "../leaderboard/", None),
        ),
        LEADERBOARD / "index.html": (
            ("Overview", "../", None),
            ("Tutorial", "../tutorial/", None),
            ("First submission", "../start/", None),
            ("Submission feedback", "../submission-feedback/", None),
            ("Leaderboard", "./", "page"),
        ),
    }

    for page, expected_links in pages.items():
        html, parser = parse_page(page)

        assert parser.site_nav_links == list(expected_links)
        assert ">Mini workshop</a>" not in html


def test_tutorial_is_the_six_case_mini_workshop_route() -> None:
    page = TUTORIAL / "index.html"

    assert page.is_file()
    html, parser = parse_page(page)
    assert parser.h1_count == 1
    assert parser.has_skip_link
    assert {"header", "main", "section", "nav", "footer"} <= set(parser.tags)
    assert "Learn Opik with six flagged runs." in html
    assert html.count('class="case"') == 6
    assert html.count("Reveal Case ") == 6
    assert "hkpug-opik-mini-workshop-onboarding.zip" in html
    assert '<a href="./" aria-current="page">Tutorial</a>' in html


def test_mini_workshop_copies_all_questions_answers_and_local_artifacts() -> None:
    html, _ = parse_page(TUTORIAL / "index.html")

    for title in (
        "Policy evidence does not match customer",
        "Slow run with broad retrieval fallback",
        "Tool result is confident but input is wrong",
        "Streamed draft was persisted after cutoff",
        "Issue summary contains unsafe comment text",
        "Release candidate looks good but gate is weak",
    ):
        assert title in html
    for answer in (
        "eligible-30-day-refund",
        "001.retrieve_policy",
        "refund-hk-pro-2026",
        "activated-not-refundable",
        "002.retrieve_policy_primary",
        "002.retrieve_policy_fallback",
        "weaker-evidence",
        "manual-review",
        "003.calculate_refund_eligibility",
        "product=pro",
        "mapping-failure",
        "004.stream_policy_summary",
        "length",
        "004.persist_customer_answer",
        "finish-reason-check",
        "issue-4812-attacker-comment",
        "005.build_issue_prompt",
        "005.postprocess_guardrail",
        "block-or-rewrite",
        "prompt-v2",
        "prompt-v3",
        "answer_relevance",
        "faithfulness-expert-gate",
    ):
        assert answer in html
    for asset in (
        "hkpug-opik-mini-workshop-onboarding.zip",
        "hkpug-opik-mini-workshop-onboarding.zip.sha256",
        "opik-select-workshop-project.png",
        "opik-select-traces-tab.png",
    ):
        assert (TUTORIAL / "assets" / asset).is_file()
    assert "Experiments" in html
    assert "43 spans" in html
    assert "issues/new/choose" not in html
    assert "group-00.opik-workshop.python.hk" not in html


def test_legacy_opik_route_redirects_to_submission_feedback_with_url_state() -> None:
    html, _ = parse_page(OPIK / "index.html")

    assert '<link rel="canonical" href="../submission-feedback/">' in html
    assert '<meta name="robots" content="noindex">' in html
    assert (
        'location.replace("../submission-feedback/" + location.search + location.hash);'
        in html
    )
    assert (
        '<a href="../submission-feedback/">Continue to the submission feedback guide</a>'
        in html
    )
    for moved_content in (
        "Start Opik locally",
        "hkpug-opik-helper",
        "tutorial-section",
        "site-nav",
    ):
        assert moved_content not in html


def test_participant_pages_distinguish_onboarding_from_submission_feedback() -> None:
    tutorial_page = TUTORIAL / "index.html"
    feedback_page = SUBMISSION_FEEDBACK / "index.html"

    assert tutorial_page.is_file()
    assert feedback_page.is_file()
    overview_html, overview = parse_page(DASHBOARD / "index.html")
    start_html, start = parse_page(START / "index.html")
    tutorial_html, _ = parse_page(tutorial_page)
    feedback_html, _ = parse_page(feedback_page)

    assert overview_html.count('href="tutorial/"') >= 3
    assert overview_html.count('href="submission-feedback/"') >= 3
    assert any(
        anchor.get("href") == "tutorial/"
        and anchor.get("class") == "button button-primary"
        for anchor in overview.anchors
    )
    assert any(
        anchor.get("href") == "tutorial/" and anchor.get("class") == "route-link"
        for anchor in overview.anchors
    )
    assert start_html.count('href="../tutorial/"') >= 2
    assert start_html.count('href="../submission-feedback/"') >= 3
    assert any(
        anchor.get("href") == "../submission-feedback/"
        and anchor.get("class") == "button button-primary"
        for anchor in start.anchors
    )
    assert '<a href="./" aria-current="page">Tutorial</a>' in tutorial_html
    assert '<a href="./" aria-current="page">Submission feedback</a>' in feedback_html
    assert 'href="opik/"' not in overview_html
    assert 'href="../opik/"' not in start_html


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


def test_submission_feedback_guide_uses_only_public_helper_commands() -> None:
    page = SUBMISSION_FEEDBACK / "index.html"

    assert page.is_file()
    html, parser = parse_page(page)

    assert parser.h1_count == 1
    assert parser.has_skip_link
    assert {"header", "main", "section", "nav", "footer"} <= set(parser.tags)
    for text in (
        "Inspect submission feedback in Opik",
        "Open the bot's score comment",
        "The GitHub download is a ZIP archive",
        "Extract the ZIP archive",
        "Start Opik locally",
        "./opik.sh",
        "hkpug-opik-helper decrypt",
        "hkpug-opik-helper load",
        "submission-feedback.cms",
        "http://localhost:5173",
        "Open the project named in the helper output",
    ):
        assert text in html
    assert "../start/" in html
    assert "releases/latest" in html
    for noise in (
        ".github/tournament",
        "import_opik.py",
        "uv run",
        "HKPUG Mini Workshop",
        "group-00.opik-workshop.python.hk",
        "discovery-feedback.cms",
    ):
        assert noise not in html


def test_submission_feedback_guide_explains_the_tournament_trace_contract() -> None:
    page = SUBMISSION_FEEDBACK / "index.html"

    assert page.is_file()
    html, _ = parse_page(page)

    assert (
        "Every scored attempt evaluates all 50 cases: 40 discovery cases and 10 "
        "holdout cases."
    ) in html
    assert "The bundle imports exactly 40 discovery traces." in html
    assert (
        "The 10 holdout cases never appear as traces; their results are aggregate-only."
    ) in html
    assert (
        "Each discovery trace has a <code>model.answer</code> span for the response "
        "and an <code>evaluation.judge</code> span for the evaluation."
    ) in html
    assert (
        "Use the seven score columns to find a pattern: JSON schema, Citation "
        "validity, Evidence coverage, Escalation, Answer relevance, Instruction "
        "following, and Faithfulness."
    ) in html


def test_submission_feedback_guide_turns_scores_into_targeted_prompt_changes() -> None:
    page = SUBMISSION_FEEDBACK / "index.html"

    assert page.is_file()
    html, _ = parse_page(page)

    for text in (
        "Improve one weakness at a time",
        "Fix deterministic failures first",
        "Score signal",
        "What a low score usually means",
        "Prompt change to test",
        "JSON schema",
        "Citation validity",
        "Evidence coverage",
        "Escalation",
        "Answer relevance",
        "Instruction following",
        "Faithfulness",
        "Choose one repeated weakness",
        "Do not optimize one trace in isolation",
        "A longer prompt is not automatically a stronger prompt.",
    ):
        assert text in html

    assert "Copy this winning prompt" not in html
    assert "hidden answer" not in html.lower()


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
        "score-history-chart",
        "score-history-empty",
        "score-history-legend",
        "score-history-range",
        "score-history-submissions",
        "team-detail",
        "criterion-breakdown",
    } <= parser.ids
    assert "../styles.css" in parser.links
    assert "app.js?v=10" in parser.scripts
    assert "No scored attempts yet" in html
    assert "could not be loaded" in html


def test_leaderboard_script_uses_public_json_and_safe_dom_updates() -> None:
    script = (LEADERBOARD / "app.js").read_text(encoding="utf-8")

    assert 'fetch("leaderboard.json"' in script
    assert "textContent" in script
    assert "innerHTML" not in script
    assert "renderScoreHistory" in script
    assert "scoreBounds" in script
    assert "runningBestScores" in script
    assert "Math.max(bestScore, run.overall_score)" in script
    assert 'path += ` H ${point.x} V ${point.y}`' in script
    assert 'historyChart.removeAttribute("hidden")' in script
    assert "Math.max(0" in script
    assert "Math.min(100" in script
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
    assert leaderboard.challenge.max_daily_attempts == 8
    assert leaderboard.challenge.weights.discovery == 0.75
    assert leaderboard.challenge.weights.holdout == 0.25
    assert leaderboard.teams == ()
