from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hkpug_challenge.difficulty_experiment import (
    adversarial_case,
    gated_score,
    select_balanced_cases,
    select_distractor_context,
)
from hkpug_challenge.evaluation_bank import (
    ARCHETYPES,
    EvaluationCase,
    EvaluationReference,
    EvaluationRubric,
)


def make_case(index: int, archetype: str) -> EvaluationCase:
    return EvaluationCase(
        case_id=f"CASE-{index:02d}",
        partition="discovery",
        domain=f"domain-{index}",
        difficulty="hard",
        archetype=archetype,
        question="What should support do?",
        context_files=("contexts/company_handbook.md", "contexts/domain.md"),
        reference=EvaluationReference(
            answer="Use active policy.",
            citations=("DOM-POL-001",),
            escalate=True,
            key_points=("Use active policy",),
        ),
        rubric=EvaluationRubric(
            required_citation_groups=(("DOM-POL-001",),),
            required_points=("one", "two", "three", "four"),
            prohibited_claims=("the retired exception controls",),
            non_authoritative_evidence=("DOM-ARCH-009",),
        ),
    )


def make_result(**overrides: object) -> dict[str, Any]:
    result: dict[str, Any] = {
        "score": 94.0,
        "criteria": {
            "json_schema": 10.0,
            "citation_validity": 10.0,
            "evidence_coverage": 10.0,
            "escalation": 10.0,
        },
        "judge": {
            "audit": {
                "required_points_met": [0, 1, 2, 3],
                "prohibited_claims_present": [],
                "non_authoritative_evidence_used": [],
            }
        },
    }
    result.update(overrides)
    return result


def test_select_balanced_cases_uses_each_archetype_and_distinct_domains() -> None:
    cases = tuple(
        make_case(index, archetype) for index, archetype in enumerate(ARCHETYPES)
    )

    selected = select_balanced_cases(cases)

    assert tuple(case.archetype for case in selected) == ARCHETYPES
    assert len({case.domain for case in selected}) == len(ARCHETYPES)


def test_adversarial_case_adds_prohibited_customer_instruction() -> None:
    case = make_case(1, ARCHETYPES[0])

    changed = adversarial_case(case)

    assert changed.case_id == case.case_id
    assert "DOM-ARCH-009" in changed.question
    assert "retired exception controls" in changed.question
    assert changed.question != case.question


def test_select_distractor_context_excludes_selected_and_handbook(
    tmp_path: Path,
) -> None:
    contexts = tmp_path / "contexts"
    contexts.mkdir()
    for name in ("company_handbook.md", "billing.md", "refunds.md"):
        (contexts / name).write_text(f"# {name}\n", encoding="utf-8")

    selected = select_distractor_context(
        public_directory=tmp_path,
        case_id="CASE-01",
        selected_contexts=("contexts/billing.md",),
    )

    assert selected == "contexts/refunds.md"


def test_gated_score_preserves_fully_compliant_result() -> None:
    score = gated_score(make_case(1, ARCHETYPES[0]), make_result())

    assert score.score == 94.0
    assert score.caps == ()


def test_gated_score_caps_critical_failures() -> None:
    result = make_result(
        criteria={
            "json_schema": 10.0,
            "citation_validity": 10.0,
            "evidence_coverage": 5.0,
            "escalation": 0.0,
        },
        judge={
            "audit": {
                "required_points_met": [0, 1, 2],
                "prohibited_claims_present": [0],
                "non_authoritative_evidence_used": ["DOM-ARCH-009"],
            }
        },
    )

    score = gated_score(make_case(1, ARCHETYPES[0]), result)

    assert score.score == 50.0
    assert score.caps == (
        "incomplete_evidence",
        "wrong_escalation",
        "missing_required_points",
        "unsafe_authority",
    )


def test_gated_score_rejects_invalid_json() -> None:
    result = make_result(
        criteria={
            "json_schema": 0.0,
            "citation_validity": 0.0,
            "evidence_coverage": 0.0,
            "escalation": 0.0,
        }
    )

    assert gated_score(make_case(1, ARCHETYPES[0]), result).score == 0.0


def test_select_balanced_cases_fails_without_distinct_domains() -> None:
    cases = tuple(
        EvaluationCase(
            **{
                **make_case(index, archetype).__dict__,
                "domain": "one-domain",
            }
        )
        for index, archetype in enumerate(ARCHETYPES)
    )

    with pytest.raises(ValueError, match="distinct domain"):
        select_balanced_cases(cases)
