from __future__ import annotations

import json
import stat
from collections import Counter
from pathlib import Path
from typing import Any, Callable, cast

import pytest

from hkpug_challenge import (
    HiddenBank,
    build_attempt_suite,
    build_hidden_bank,
    load_hidden_bank,
)


DOMAINS = (
    ("account-access", "ACC"),
    ("api-limits", "API"),
    ("billing", "BIL"),
    ("data-retention", "RET"),
    ("integrations", "INT"),
    ("privacy", "PRI"),
    ("refunds", "REF"),
    ("security", "SEC"),
    ("service-incidents", "INC"),
    ("subscriptions", "SUB"),
)
DATASET_VERSION = "2026-07-12"
RUBRIC_VERSION = "2026-07-12"
JsonDict = dict[str, Any]


def write_public_dataset(root: Path) -> tuple[Path, list[JsonDict]]:
    public_directory = root / "public"
    contexts_directory = public_directory / "contexts"
    contexts_directory.mkdir(parents=True)
    handbook_path = contexts_directory / "company_handbook.md"
    handbook_path.write_text(
        "# Company handbook\n\n## [HB-GOV-001]\nGeneral policy reference.\n",
        encoding="utf-8",
    )

    cases: list[JsonDict] = []
    difficulties = ["easy"] * 10 + ["standard"] * 30 + ["hard"] * 10
    difficulty_index = 0
    for domain, prefix in DOMAINS:
        for family_number in range(1, 6):
            family_id = f"{prefix}-{family_number:02d}"
            domain_context = f"contexts/{family_id.lower()}.md"
            (contexts_directory / f"{family_id.lower()}.md").write_text(
                (
                    f"# {family_id}\n\n"
                    f"## [{prefix}-AUTH-{family_number:02d}]\nAuthoritative policy.\n\n"
                    f"## [{prefix}-ARCH-{family_number:02d}]\nArchived note.\n"
                ),
                encoding="utf-8",
            )
            cases.append(
                {
                    "id": family_id,
                    "domain": domain,
                    "difficulty": difficulties[difficulty_index],
                    "question": f"Public question for {family_id}",
                    "context_files": [
                        "contexts/company_handbook.md",
                        domain_context,
                    ],
                }
            )
            difficulty_index += 1

    (public_directory / "cases.json").write_text(
        json.dumps({"version": 1, "cases": cases}, indent=2) + "\n",
        encoding="utf-8",
    )
    return public_directory, cases


def write_hidden_inputs(root: Path, cases: list[JsonDict]) -> Path:
    input_directory = root / "input"
    input_directory.mkdir(parents=True)
    cases_by_domain = {
        domain: [case for case in cases if case["domain"] == domain]
        for domain, _prefix in DOMAINS
    }

    for domain, prefix in DOMAINS:
        variants: list[JsonDict] = []
        for case in cases_by_domain[domain]:
            family_suffix = int(case["id"].split("-")[1])
            for slot in range(1, 9):
                variants.append(
                    {
                        "variant_id": f"{case['id']}-H{slot}",
                        "family_id": case["id"],
                        "slot": slot,
                        "domain": domain,
                        "difficulty": case["difficulty"],
                        "question": f"Hidden question for {case['id']} slot {slot}",
                        "context_files": case["context_files"],
                        "reference": {
                            "answer": f"Answer for {case['id']} slot {slot}.",
                            "citations": [f"{prefix}-AUTH-{family_suffix:02d}"],
                            "escalate": slot == 8,
                            "key_points": [f"Point for {case['id']} slot {slot}"],
                        },
                        "rubric": {
                            "required_citation_groups": [
                                [f"{prefix}-AUTH-{family_suffix:02d}"]
                            ],
                            "required_points": [f"Mention {case['id']} slot {slot}"],
                            "prohibited_claims": [
                                f"Do not invent facts for {case['id']} slot {slot}"
                            ],
                            "non_authoritative_evidence": [
                                "HB-GOV-001",
                                f"{prefix}-ARCH-{family_suffix:02d}",
                            ],
                        },
                    }
                )
        payload = {
            "schema_version": 1,
            "dataset_version": DATASET_VERSION,
            "rubric_version": RUBRIC_VERSION,
            "variants": variants,
        }
        (input_directory / f"{domain}.json").write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
    return input_directory


def build_synthetic_hidden_bank(root: Path) -> tuple[Path, Path]:
    public_directory, cases = write_public_dataset(root)
    input_directory = write_hidden_inputs(root, cases)
    return public_directory, input_directory


def load_domain_payloads(input_directory: Path) -> list[JsonDict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(input_directory.glob("*.json"))
    ]


def write_domain_payloads(input_directory: Path, payloads: list[JsonDict]) -> None:
    for path, payload in zip(
        sorted(input_directory.glob("*.json")), payloads, strict=True
    ):
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_build_hidden_bank_writes_canonical_json_and_deterministic_suites(
    tmp_path: Path,
) -> None:
    public_directory, input_directory = build_synthetic_hidden_bank(tmp_path)
    output_path = tmp_path / "artifacts" / "hidden_bank.json"

    bank = build_hidden_bank(
        input_directory=input_directory,
        output_path=output_path,
        public_directory=public_directory,
    )

    assert isinstance(bank, HiddenBank)
    assert output_path.exists()
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600

    output_text = output_path.read_text(encoding="utf-8")
    assert output_text.index('"schema_version"') < output_text.index(
        '"dataset_version"'
    )
    assert output_text.index('"dataset_version"') < output_text.index(
        '"rubric_version"'
    )
    assert output_text.index('"rubric_version"') < output_text.index('"variants"')

    reloaded = load_hidden_bank(output_path, public_directory=public_directory)
    assert reloaded == bank
    assert len(reloaded.variants) == 400

    attempt_one = build_attempt_suite(reloaded, team_id="team-alpha", attempt=1)
    assert len(attempt_one) == 50
    assert len({variant.family_id for variant in attempt_one}) == 50
    assert Counter(variant.domain for variant in attempt_one) == Counter(
        {domain: 5 for domain, _prefix in DOMAINS}
    )
    assert Counter(variant.difficulty for variant in attempt_one) == Counter(
        {"easy": 10, "standard": 30, "hard": 10}
    )

    slots = {
        build_attempt_suite(reloaded, team_id="team-alpha", attempt=attempt)[0].slot
        for attempt in range(1, 9)
    }
    assert slots == set(range(1, 9))
    assert build_attempt_suite(
        reloaded, team_id="team-alpha", attempt=3
    ) == build_attempt_suite(reloaded, team_id="team-alpha", attempt=3)


Mutation = Callable[[list[JsonDict]], None]


def mutate_duplicate_question(payloads: list[JsonDict]) -> None:
    cast_variant(payloads, 0, 0)["question"] = "Hidden question for ACC-01 slot 2"


def mutate_reference_answer_too_long(payloads: list[JsonDict]) -> None:
    cast_reference(payloads, 0, 0)["answer"] = " ".join(["word"] * 101)


def mutate_undisclosed_context(payloads: list[JsonDict]) -> None:
    cast_variant(payloads, 0, 0)["context_files"] = [
        "contexts/company_handbook.md",
        "contexts/api-01.md",
    ]


def mutate_unknown_reference_citation(payloads: list[JsonDict]) -> None:
    cast_reference(payloads, 0, 0)["citations"] = ["UNKNOWN-ID-001"]


def mutate_variant_id_collision(payloads: list[JsonDict]) -> None:
    cast_variant(payloads, 0, 0)["variant_id"] = "ACC-01"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (mutate_duplicate_question, "duplicate question"),
        (mutate_reference_answer_too_long, "100 words"),
        (mutate_undisclosed_context, "undisclosed context"),
        (mutate_unknown_reference_citation, "unknown citation"),
        (mutate_variant_id_collision, "disjoint"),
    ],
)
def test_build_hidden_bank_rejects_hidden_bank_invariant_violations(
    tmp_path: Path,
    mutate: Mutation,
    message: str,
) -> None:
    public_directory, input_directory = build_synthetic_hidden_bank(tmp_path)
    payloads = load_domain_payloads(input_directory)
    mutate(payloads)
    write_domain_payloads(input_directory, payloads)

    with pytest.raises(ValueError, match=message):
        build_hidden_bank(
            input_directory=input_directory,
            output_path=tmp_path / "hidden_bank.json",
            public_directory=public_directory,
        )


def test_build_hidden_bank_rejects_tracked_output_paths_but_allows_local(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repo"
    (repository_root / ".git").mkdir(parents=True)
    public_directory, input_directory = build_synthetic_hidden_bank(repository_root)

    with pytest.raises(ValueError, match=r"\.local"):
        build_hidden_bank(
            input_directory=input_directory,
            output_path=repository_root / "hidden_bank.json",
            public_directory=public_directory,
            repository_root=repository_root,
        )

    output_path = repository_root / ".local" / "hidden" / "hidden_bank.json"
    bank = build_hidden_bank(
        input_directory=input_directory,
        output_path=output_path,
        public_directory=public_directory,
        repository_root=repository_root,
    )

    assert isinstance(bank, HiddenBank)
    assert output_path.exists()


def test_question_review_doc_starts_without_hidden_content_approval() -> None:
    review_path = (
        Path(__file__).resolve().parents[1] / "docs" / "qa" / "question-review.md"
    )
    review_text = review_path.read_text(encoding="utf-8")

    assert (
        "No hidden question content has been reviewed or approved yet." in review_text
    )
    assert "Human Fairness Review" in review_text


def cast_reference(
    payloads: list[JsonDict], domain_index: int, variant_index: int
) -> JsonDict:
    reference = cast_variant(payloads, domain_index, variant_index)["reference"]
    assert isinstance(reference, dict)
    return cast(JsonDict, reference)


def cast_variant(
    payloads: list[JsonDict], domain_index: int, variant_index: int
) -> JsonDict:
    variants = payloads[domain_index]["variants"]
    assert isinstance(variants, list)
    typed_variants = cast(list[JsonDict], variants)
    variant = typed_variants[variant_index]
    assert isinstance(variant, dict)
    return variant
