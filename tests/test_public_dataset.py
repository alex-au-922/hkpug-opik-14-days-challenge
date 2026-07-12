from __future__ import annotations

import json
import math
import re
import statistics
from collections import Counter
from pathlib import Path

import pytest

from hkpug_challenge.dataset import load_public_cases
from hkpug_challenge.messages import SYSTEM_PROMPT, render_messages
from hkpug_challenge.models import ChallengeAnswer, PublicCase, validate_answer


EXPECTED_DOMAINS = {
    "account-access",
    "api-limits",
    "billing",
    "data-retention",
    "integrations",
    "privacy",
    "refunds",
    "security",
    "service-incidents",
    "subscriptions",
}
EVIDENCE_ID_PATTERN = r"^[A-Z][A-Z0-9]+(?:-[A-Z0-9]+){2,}$"
EXPECTED_REVIEWED_QUESTIONS = {
    "REF-02": (
        "The payment ledger for an activated HK Starter annual subscription shows "
        "one valid subscription purchase with a settled charge and one additional "
        "settled duplicate charge caused by confirmed checkout incident "
        "PAY-2026-0512. Which charge should be refunded?"
    ),
    "SUB-04": (
        "An administrator attempted to reverse a scheduled cancellation before the "
        "paid-through expiry, but confirmed billing-portal incident BP-2026-0602 "
        "prevented the reversal and no billing event was written. The request is "
        "within seven days of expiry. May Incident Command restore the prior "
        "renewal date?"
    ),
    "INT-04": (
        "The customer-configurable shared field `renewal_contact_email` was changed "
        "in HarbourCloud at 09:01:10 UTC and in the CRM at 09:02:25 UTC, so both "
        "changes occurred within the same two-minute sync window before the "
        "09:03:00 UTC sync. Which connector state applies?"
    ),
    "SEC-03": (
        "A reproducible vulnerability report contains live access tokens. What "
        "immediate credential handling is required before Product Security "
        "review?"
    ),
}


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def build_case() -> PublicCase:
    return PublicCase(
        id="REF-01",
        domain="refunds",
        difficulty="easy",
        question="Can this purchase be refunded?",
        context="## [REF-POL-001]\nSettled first purchases may be refunded.",
        context_files=("contexts/company_handbook.md", "contexts/refunds.md"),
        evidence_ids=frozenset({"REF-POL-001"}),
    )


def test_public_dataset_has_fifty_balanced_cases() -> None:
    cases = load_public_cases()

    assert len(cases) == 50
    assert len({case.id for case in cases}) == 50
    assert Counter(case.domain for case in cases) == Counter(
        {domain: 5 for domain in EXPECTED_DOMAINS}
    )
    assert Counter(case.difficulty for case in cases) == Counter(
        {"easy": 10, "standard": 30, "hard": 10}
    )


def test_each_case_uses_two_context_files_and_valid_evidence_ids() -> None:
    cases = load_public_cases()

    for case in cases:
        assert len(case.context_files) == 2, case.id
        assert len(set(case.context_files)) == 2, case.id
        assert all(path.startswith("contexts/") for path in case.context_files), case.id
        assert case.evidence_ids, case.id
        for evidence_id in case.evidence_ids:
            assert re.match(EVIDENCE_ID_PATTERN, evidence_id), (case.id, evidence_id)


def test_average_rendered_context_stays_in_the_4400_token_band() -> None:
    estimates = [estimate_tokens(case.context) for case in load_public_cases()]

    assert statistics.mean(estimates) >= 4_100
    assert statistics.mean(estimates) <= 4_700


def test_resolved_public_qa_requirements_are_present() -> None:
    cases = {case.id: case for case in load_public_cases()}

    assert "read-only GitHub issue import" in cases["INT-01"].question
    assert "authorization marked `reversal_requested`" in cases["REF-05"].question
    assert "destination administrator whose HarbourCloud user is already verified" in (
        cases["ACC-04"].question
    )


def test_reviewed_cases_use_deterministic_single_decision_questions() -> None:
    cases = {case.id: case for case in load_public_cases()}

    assert {
        case_id: cases[case_id].question for case_id in EXPECTED_REVIEWED_QUESTIONS
    } == EXPECTED_REVIEWED_QUESTIONS


def test_render_messages_embeds_context_question_and_json_contract() -> None:
    case = build_case()

    messages = render_messages(case)

    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert messages[1]["role"] == "user"
    assert case.context in messages[1]["content"]
    assert case.question in messages[1]["content"]
    assert '"citations"' in messages[1]["content"]


def test_validate_answer_accepts_a_valid_payload() -> None:
    answer = validate_answer(
        build_case(),
        json.dumps(
            {
                "answer": "This settled first purchase qualifies for refund review.",
                "citations": ["REF-POL-001"],
                "escalate": False,
            }
        ),
    )

    assert answer == ChallengeAnswer(
        answer="This settled first purchase qualifies for refund review.",
        citations=("REF-POL-001",),
        escalate=False,
    )


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ('{"answer":"ok","citations":["REF-POL-001"]}', "exactly"),
        (
            '{"answer":"ok","citations":["REF-POL-001"],"escalate":false,"note":"x"}',
            "exactly",
        ),
        (
            '{"answer":"ok","citations":["REF-POL-001","REF-POL-001"],"escalate":false}',
            "unique",
        ),
        ('{"answer":"ok","citations":["UNKNOWN"],"escalate":false}', "unknown"),
        ('{"answer":"ok","citations":["REF-POL-001"],"escalate":"no"}', "boolean"),
    ],
)
def test_validate_answer_rejects_invalid_contract_values(
    response: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_answer(build_case(), response)


def test_validate_answer_rejects_answers_over_one_hundred_words() -> None:
    response = json.dumps(
        {
            "answer": " ".join(["word"] * 101),
            "citations": ["REF-POL-001"],
            "escalate": False,
        }
    )

    with pytest.raises(ValueError, match="100 words"):
        validate_answer(build_case(), response)


def test_load_public_cases_rejects_context_paths_outside_the_dataset(
    tmp_path: Path,
) -> None:
    public_directory = tmp_path / "public"
    contexts_directory = public_directory / "contexts"
    contexts_directory.mkdir(parents=True)
    (contexts_directory / "company_handbook.md").write_text(
        "# Handbook\n\n## [HC-GOV-001]\nAuthority."
    )
    (public_directory / "cases.json").write_text(
        json.dumps(
            {
                "version": 1,
                "cases": [
                    {
                        "id": "REF-01",
                        "domain": "refunds",
                        "difficulty": "easy",
                        "question": "Test question",
                        "context_files": [
                            "contexts/company_handbook.md",
                            "../secrets.md",
                        ],
                    }
                ],
            }
        )
    )

    with pytest.raises(ValueError, match="outside the dataset"):
        load_public_cases(public_directory)
