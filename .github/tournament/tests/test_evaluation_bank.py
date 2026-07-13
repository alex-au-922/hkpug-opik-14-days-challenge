from __future__ import annotations

import importlib.util
import json
import sys
import stat
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Callable, cast

import pytest

from hkpug_challenge import (
    EvaluationBank,
    EvaluationCase,
    build_evaluation_bank,
    load_evaluation_bank,
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
ARCHETYPES = (
    "direct_policy_lookup",
    "multi_source_synthesis",
    "conflicting_or_stale_evidence",
    "prompt_injection_or_untrusted_evidence",
    "ambiguous_authority_or_escalation",
)
ARCHETYPE_DIFFICULTIES = {
    "direct_policy_lookup": "easy",
    "multi_source_synthesis": "standard",
    "conflicting_or_stale_evidence": "standard",
    "prompt_injection_or_untrusted_evidence": "hard",
    "ambiguous_authority_or_escalation": "hard",
}
ARCHETYPE_MINIMUMS: dict[str, dict[str, int]] = {
    "direct_policy_lookup": {
        "citation_groups": 1,
        "required_points": 2,
        "prohibited_claims": 2,
        "non_authoritative_evidence": 0,
    },
    "multi_source_synthesis": {
        "citation_groups": 2,
        "required_points": 3,
        "prohibited_claims": 3,
        "non_authoritative_evidence": 0,
    },
    "conflicting_or_stale_evidence": {
        "citation_groups": 2,
        "required_points": 3,
        "prohibited_claims": 3,
        "non_authoritative_evidence": 1,
    },
    "prompt_injection_or_untrusted_evidence": {
        "citation_groups": 2,
        "required_points": 4,
        "prohibited_claims": 4,
        "non_authoritative_evidence": 1,
    },
    "ambiguous_authority_or_escalation": {
        "citation_groups": 2,
        "required_points": 4,
        "prohibited_claims": 4,
        "non_authoritative_evidence": 0,
    },
}


def write_public_dataset(root: Path) -> tuple[Path, list[JsonDict]]:
    public_directory = root / "public"
    contexts_directory = public_directory / "contexts"
    contexts_directory.mkdir(parents=True)
    handbook_path = contexts_directory / "company_handbook.md"
    handbook_path.write_text(
        (
            "# Company handbook\n\n"
            "## [HB-GOV-001]\nGeneral policy reference.\n\n"
            "## [HB-ESC-001]\nEscalate when policy leaves authority unresolved.\n"
        ),
        encoding="utf-8",
    )

    cases: list[JsonDict] = []
    difficulties = ["easy", "standard", "standard", "standard", "hard"]
    for domain, prefix in DOMAINS:
        context_path = f"contexts/{domain.replace('-', '_')}.md"
        (contexts_directory / f"{domain.replace('-', '_')}.md").write_text(
            (
                f"# {domain}\n\n"
                f"## [{prefix}-AUTH-001]\nAuthoritative policy.\n\n"
                f"## [{prefix}-AUTH-002]\nSecond authoritative clause.\n\n"
                f"## [{prefix}-ARCH-001]\nArchived guidance.\n"
            ),
            encoding="utf-8",
        )
        for index, difficulty in enumerate(difficulties, start=1):
            cases.append(
                {
                    "id": f"{prefix}-{index:02d}",
                    "domain": domain,
                    "difficulty": difficulty,
                    "question": f"Public practice question for {prefix}-{index:02d}",
                    "context_files": [
                        "contexts/company_handbook.md",
                        context_path,
                    ],
                }
            )

    (public_directory / "cases.json").write_text(
        json.dumps({"version": 1, "cases": cases}, indent=2) + "\n",
        encoding="utf-8",
    )
    return public_directory, cases


def write_evaluation_inputs(root: Path) -> tuple[Path, list[JsonDict]]:
    public_directory, public_cases = write_public_dataset(root)
    input_directory = root / ".local" / "evaluation" / "domains"
    input_directory.mkdir(parents=True)

    public_case_by_domain = {
        domain: [case for case in public_cases if case["domain"] == domain]
        for domain, _prefix in DOMAINS
    }

    for domain_position, (domain, prefix) in enumerate(DOMAINS):
        cases: list[JsonDict] = []
        holdout_position = domain_position // 2 + 1
        for index, public_case in enumerate(public_case_by_domain[domain], start=1):
            partition = "holdout" if index == holdout_position else "discovery"
            archetype = ARCHETYPES[index - 1]
            difficulty = ARCHETYPE_DIFFICULTIES[archetype]
            minimums = ARCHETYPE_MINIMUMS[archetype]
            reference_citations = ["HB-GOV-001"]
            required_citation_groups: list[list[str]] = [["HB-GOV-001"]]
            if minimums["citation_groups"] >= 2:
                reference_citations.append(f"{prefix}-AUTH-001")
                required_citation_groups.append(
                    [f"{prefix}-AUTH-001", f"{prefix}-AUTH-002"]
                )
            required_points = [
                f"Required point {point} for {prefix}-EVAL-{index:02d}"
                for point in range(1, minimums["required_points"] + 1)
            ]
            prohibited_claims = [
                f"Prohibited claim {claim} for {prefix}-EVAL-{index:02d}"
                for claim in range(1, minimums["prohibited_claims"] + 1)
            ]
            non_authoritative_evidence = [
                f"{prefix}-ARCH-00{entry}"
                for entry in range(1, minimums["non_authoritative_evidence"] + 1)
            ]
            cases.append(
                {
                    "case_id": f"{prefix}-EVAL-{index:02d}",
                    "partition": partition,
                    "domain": domain,
                    "difficulty": difficulty,
                    "archetype": archetype,
                    "question": (
                        f"Private evaluation question for {prefix}-EVAL-{index:02d}"
                    ),
                    "context_files": public_case["context_files"],
                    "reference": {
                        "answer": f"Approved answer for {prefix}-EVAL-{index:02d}.",
                        "citations": reference_citations,
                        "escalate": partition == "holdout",
                        "key_points": [
                            f"Key point for {prefix}-EVAL-{index:02d}",
                        ],
                    },
                    "rubric": {
                        "required_citation_groups": required_citation_groups,
                        "required_points": required_points,
                        "prohibited_claims": prohibited_claims,
                        "non_authoritative_evidence": non_authoritative_evidence,
                    },
                }
            )

        payload = {
            "schema_version": 1,
            "dataset_version": DATASET_VERSION,
            "rubric_version": RUBRIC_VERSION,
            "cases": cases,
        }
        (input_directory / f"{domain}.json").write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )

    return public_directory, public_cases


def build_synthetic_evaluation_bank(root: Path) -> tuple[Path, Path, list[JsonDict]]:
    public_directory, public_cases = write_evaluation_inputs(root)
    input_directory = root / ".local" / "evaluation" / "domains"
    return public_directory, input_directory, public_cases


def build_synthetic_evaluation_bank_in_repo(
    root: Path,
) -> tuple[Path, Path, Path, list[JsonDict]]:
    repository_root = root / "repo"
    repository_root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repository_root)], check=True)
    (repository_root / ".gitignore").write_text(".local/\n", encoding="utf-8")
    public_directory, input_directory, public_cases = build_synthetic_evaluation_bank(
        repository_root
    )
    return repository_root, public_directory, input_directory, public_cases


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


def test_build_evaluation_bank_writes_canonical_json_and_fixed_partitions(
    tmp_path: Path,
) -> None:
    repository_root, public_directory, input_directory, public_cases = (
        build_synthetic_evaluation_bank_in_repo(tmp_path)
    )
    output_path = repository_root / ".local" / "evaluation" / "evaluation_bank.json"

    bank = build_evaluation_bank(
        input_directory=input_directory,
        public_directory=public_directory,
        repository_root=repository_root,
        output_path=output_path,
    )

    assert isinstance(bank, EvaluationBank)
    assert output_path.exists()
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600

    output_text = output_path.read_text(encoding="utf-8")
    assert output_text.index('"schema_version"') < output_text.index(
        '"dataset_version"'
    )
    assert output_text.index('"dataset_version"') < output_text.index(
        '"rubric_version"'
    )
    assert output_text.index('"rubric_version"') < output_text.index('"cases"')
    assert '"variants"' not in output_text

    reloaded = load_evaluation_bank(output_path, public_directory=public_directory)
    assert reloaded == bank
    assert len(reloaded.cases) == 50
    assert all(isinstance(case, EvaluationCase) for case in reloaded.cases)
    assert Counter(case.partition for case in reloaded.cases) == Counter(
        {"discovery": 40, "holdout": 10}
    )
    assert Counter(case.domain for case in reloaded.cases) == Counter(
        {domain: 5 for domain, _prefix in DOMAINS}
    )
    assert Counter(case.archetype for case in reloaded.cases) == Counter(
        {archetype: 10 for archetype in ARCHETYPES}
    )
    assert Counter(case.difficulty for case in reloaded.cases) == Counter(
        {"easy": 10, "standard": 20, "hard": 20}
    )
    assert {
        partition: Counter(
            case.difficulty for case in reloaded.cases if case.partition == partition
        )
        for partition in ("discovery", "holdout")
    } == {
        "discovery": Counter({"easy": 8, "standard": 16, "hard": 16}),
        "holdout": Counter({"easy": 2, "standard": 4, "hard": 4}),
    }
    assert Counter(
        case.domain for case in reloaded.cases if case.partition == "holdout"
    ) == Counter({domain: 1 for domain, _prefix in DOMAINS})
    assert {
        domain: Counter(
            case.archetype for case in reloaded.cases if case.domain == domain
        )
        for domain, _prefix in DOMAINS
    } == {
        domain: Counter({archetype: 1 for archetype in ARCHETYPES})
        for domain, _prefix in DOMAINS
    }
    assert {
        partition: Counter(
            case.archetype for case in reloaded.cases if case.partition == partition
        )
        for partition in ("discovery", "holdout")
    } == {
        "discovery": Counter({archetype: 8 for archetype in ARCHETYPES}),
        "holdout": Counter({archetype: 2 for archetype in ARCHETYPES}),
    }
    assert {
        case.archetype: case.difficulty
        for case in reloaded.cases
        if case.domain == DOMAINS[0][0]
    } == ARCHETYPE_DIFFICULTIES
    assert all(
        case.difficulty == ARCHETYPE_DIFFICULTIES[case.archetype]
        for case in reloaded.cases
    )

    public_questions = {case["question"] for case in public_cases}
    assert not public_questions.intersection({case.question for case in reloaded.cases})


Mutation = Callable[[list[JsonDict], list[JsonDict]], None]


def mutate_duplicate_question(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    cast_case(payloads, 0, 0)["question"] = cast_case(payloads, 0, 1)["question"]


def mutate_public_question_collision(
    payloads: list[JsonDict], public_cases: list[JsonDict]
) -> None:
    cast_case(payloads, 0, 0)["question"] = public_cases[0]["question"]


def mutate_reference_answer_too_long(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    cast_reference(payloads, 0, 0)["answer"] = " ".join(["word"] * 101)


def mutate_unknown_context_file(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    cast_case(payloads, 0, 0)["context_files"] = [
        "contexts/company_handbook.md",
        "contexts/unknown.md",
    ]


def mutate_stray_public_context_file(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    cast_case(payloads, 0, 0)["context_files"] = [
        "contexts/company_handbook.md",
        "contexts/stray.md",
    ]
    cast_reference(payloads, 0, 0)["citations"] = ["HB-GOV-001", "STR-ALT-001"]
    cast_rubric(payloads, 0, 0)["required_citation_groups"] = [
        ["HB-GOV-001"],
        ["STR-ALT-001", "STR-ALT-002"],
    ]
    cast_rubric(payloads, 0, 0)["non_authoritative_evidence"] = ["STR-ARCH-001"]


def mutate_wrong_domain_published_context(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    cast_case(payloads, 0, 0)["context_files"] = [
        "contexts/company_handbook.md",
        "contexts/billing.md",
    ]
    cast_reference(payloads, 0, 0)["citations"] = ["HB-GOV-001", "BIL-AUTH-001"]
    cast_rubric(payloads, 0, 0)["required_citation_groups"] = [
        ["HB-GOV-001"],
        ["BIL-AUTH-001", "BIL-AUTH-002"],
    ]
    cast_rubric(payloads, 0, 0)["non_authoritative_evidence"] = ["BIL-ARCH-001"]


def mutate_unknown_reference_citation(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    cast_reference(payloads, 0, 0)["citations"] = ["UNKNOWN-ID-001"]


def mutate_extra_case_field(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    cast_case(payloads, 0, 0)["slot"] = 1


def mutate_extra_root_field(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    payloads[0]["variants"] = []


def mutate_second_holdout_for_domain(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    cast_case(payloads, 0, 1)["partition"] = "holdout"
    cast_case(payloads, 1, 0)["partition"] = "discovery"


def mutate_unbalanced_partition_difficulty(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    cast_case(payloads, 0, 0)["difficulty"] = "hard"
    cast_case(payloads, 0, 3)["difficulty"] = "easy"


def mutate_swapped_archetype_difficulty_labels(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    cast_case(payloads, 4, 0)["difficulty"] = "standard"
    cast_case(payloads, 4, 1)["difficulty"] = "easy"


def mutate_wrong_total_case_count(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    cases = payloads[0]["cases"]
    assert isinstance(cases, list)
    cases.pop()


def mutate_question_too_long(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    cast_case(payloads, 0, 0)["question"] = " ".join(["word"] * 81)


def mutate_duplicate_archetype_within_domain(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    cast_case(payloads, 0, 1)["archetype"] = ARCHETYPES[2]
    cast_case(payloads, 1, 2)["archetype"] = ARCHETYPES[1]


def mutate_unbalanced_archetype_partitions(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    first_domain_cases = payloads[0]["cases"]
    assert isinstance(first_domain_cases, list)
    first_domain_cases[0]["archetype"], first_domain_cases[1]["archetype"] = (
        first_domain_cases[1]["archetype"],
        first_domain_cases[0]["archetype"],
    )


def mutate_reference_misses_required_citation_group(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    cast_reference(payloads, 0, 1)["citations"] = ["HB-GOV-001"]


def mutate_reference_uses_non_authoritative_evidence(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    cast_reference(payloads, 0, 2)["citations"] = [
        "HB-GOV-001",
        "ACC-AUTH-001",
        "ACC-ARCH-001",
    ]


def mutate_archetype_minimum_violation(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    cast_rubric(payloads, 0, 0)["prohibited_claims"] = ["Only one prohibited claim."]


def mutate_multi_source_minimum_violation(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    cast_rubric(payloads, 0, 1)["prohibited_claims"] = [
        "Only one prohibited claim.",
        "Only two prohibited claims.",
    ]


def mutate_conflicting_evidence_minimum_violation(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    cast_rubric(payloads, 0, 2)["required_points"] = [
        "Only one required point.",
        "Only two required points.",
    ]


def mutate_injection_minimum_violation(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    cast_rubric(payloads, 0, 3)["prohibited_claims"] = [
        "Only one prohibited claim.",
        "Only two prohibited claims.",
        "Only three prohibited claims.",
    ]


def mutate_ambiguous_escalation_minimum_violation(
    payloads: list[JsonDict], _public_cases: list[JsonDict]
) -> None:
    cast_rubric(payloads, 0, 4)["prohibited_claims"] = [
        "Only one prohibited claim.",
        "Only two prohibited claims.",
        "Only three prohibited claims.",
    ]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (mutate_duplicate_question, "duplicate question"),
        (mutate_public_question_collision, "public practice question"),
        (mutate_reference_answer_too_long, "100 words"),
        (mutate_unknown_context_file, "unknown context file|context-file combination"),
        (mutate_stray_public_context_file, "context-file combination"),
        (mutate_wrong_domain_published_context, "context-file combination"),
        (mutate_unknown_reference_citation, "unknown citation"),
        (mutate_extra_case_field, "Extra inputs are not permitted"),
        (mutate_extra_root_field, "Extra inputs are not permitted"),
        (mutate_second_holdout_for_domain, "exactly one holdout"),
        (mutate_unbalanced_partition_difficulty, "balance difficulty"),
        (mutate_swapped_archetype_difficulty_labels, "archetype-to-difficulty mapping"),
        (mutate_wrong_total_case_count, "exactly 50 cases"),
        (mutate_question_too_long, "80 words"),
        (
            mutate_duplicate_archetype_within_domain,
            "exactly one case for each archetype",
        ),
        (mutate_unbalanced_archetype_partitions, "8 discovery and 2 holdout"),
        (
            mutate_reference_misses_required_citation_group,
            "reference citations must cover",
        ),
        (
            mutate_reference_uses_non_authoritative_evidence,
            "non-authoritative evidence",
        ),
        (mutate_archetype_minimum_violation, "minimum rubric counts"),
        (mutate_multi_source_minimum_violation, "minimum rubric counts"),
        (mutate_conflicting_evidence_minimum_violation, "minimum rubric counts"),
        (mutate_injection_minimum_violation, "minimum rubric counts"),
        (mutate_ambiguous_escalation_minimum_violation, "minimum rubric counts"),
    ],
)
def test_build_evaluation_bank_rejects_invariant_violations(
    tmp_path: Path,
    mutate: Mutation,
    message: str,
) -> None:
    repository_root, public_directory, input_directory, public_cases = (
        build_synthetic_evaluation_bank_in_repo(tmp_path)
    )
    payloads = load_domain_payloads(input_directory)
    mutate(payloads, public_cases)
    write_domain_payloads(input_directory, payloads)

    with pytest.raises(ValueError, match=message):
        build_evaluation_bank(
            input_directory=input_directory,
            public_directory=public_directory,
            repository_root=repository_root,
            output_path=repository_root
            / ".local"
            / "evaluation"
            / "evaluation_bank.json",
        )


def test_build_evaluation_bank_rejects_arbitrary_ignored_output_path(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repo"
    repository_root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repository_root)], check=True)
    (repository_root / ".gitignore").write_text(".local/\n", encoding="utf-8")
    public_directory, input_directory, _public_cases = build_synthetic_evaluation_bank(
        repository_root
    )

    with pytest.raises(ValueError, match="canonical"):
        build_evaluation_bank(
            input_directory=input_directory,
            public_directory=public_directory,
            repository_root=repository_root,
            output_path=repository_root / ".local" / "evaluation" / "other.json",
        )


def test_build_evaluation_bank_rejects_nested_repository_paths(tmp_path: Path) -> None:
    repository_root = tmp_path / "repo"
    repository_root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repository_root)], check=True)
    (repository_root / ".gitignore").write_text(".local/\n", encoding="utf-8")
    public_directory, input_directory, _public_cases = build_synthetic_evaluation_bank(
        repository_root
    )
    nested_repository = repository_root / ".local" / "evaluation"
    nested_repository.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(nested_repository)], check=True)

    with pytest.raises(ValueError, match="nested Git repository"):
        build_evaluation_bank(
            input_directory=input_directory,
            public_directory=public_directory,
            repository_root=repository_root,
            output_path=nested_repository / "evaluation_bank.json",
        )


def test_build_evaluation_bank_rejects_preexisting_symlink_output_path(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repo"
    repository_root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repository_root)], check=True)
    (repository_root / ".gitignore").write_text(".local/\n", encoding="utf-8")
    public_directory, input_directory, _public_cases = build_synthetic_evaluation_bank(
        repository_root
    )

    output_path = repository_root / ".local" / "evaluation" / "evaluation_bank.json"
    target_path = repository_root / "victim.json"
    target_path.write_text("victim\n", encoding="utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.symlink_to(target_path)

    with pytest.raises(ValueError, match="unsafe|symlink"):
        build_evaluation_bank(
            input_directory=input_directory,
            public_directory=public_directory,
            repository_root=repository_root,
            output_path=output_path,
        )

    assert target_path.read_text(encoding="utf-8") == "victim\n"


def test_build_evaluation_bank_rejects_replacement_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_root = tmp_path / "repo"
    repository_root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repository_root)], check=True)
    (repository_root / ".gitignore").write_text(".local/\n", encoding="utf-8")
    public_directory, input_directory, _public_cases = build_synthetic_evaluation_bank(
        repository_root
    )

    output_path = repository_root / ".local" / "evaluation" / "evaluation_bank.json"
    target_path = repository_root / "victim.json"
    target_path.write_text("victim\n", encoding="utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("stale\n", encoding="utf-8")

    original_os_open = __import__("os").open
    raced = {"done": False}

    def fake_open(
        path: str, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ):
        if not raced["done"] and str(path).endswith("evaluation_bank.json"):
            raced["done"] = True
            output_path.unlink()
            output_path.symlink_to(target_path)
        return original_os_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr("hkpug_challenge.evaluation_bank.os.open", fake_open)

    with pytest.raises(ValueError, match="unsafe|symlink"):
        build_evaluation_bank(
            input_directory=input_directory,
            public_directory=public_directory,
            repository_root=repository_root,
            output_path=output_path,
        )

    assert target_path.read_text(encoding="utf-8") == "victim\n"


def test_build_script_uses_trusted_script_location_for_repo_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_root = tmp_path / "authoritative"
    script_path = (
        repository_root
        / ".github"
        / "tournament"
        / "scripts"
        / "build_evaluation_bank.py"
    )
    script_path.parent.mkdir(parents=True)
    script_path.write_text("# fake script path\n", encoding="utf-8")
    input_directory = repository_root / ".local" / "evaluation" / "domains"
    input_directory.mkdir(parents=True)
    (tmp_path / "elsewhere").mkdir(parents=True)
    captured: dict[str, Path] = {}

    def fake_build_evaluation_bank(
        *,
        input_directory: Path,
        public_directory: Path = Path("/unused"),
        repository_root: Path,
        output_path: Path,
    ) -> None:
        captured["input_directory"] = input_directory
        captured["public_directory"] = public_directory
        captured["repository_root"] = repository_root
        captured["output_path"] = output_path

    script_module = load_script_module()
    monkeypatch.setattr(script_module, "__file__", str(script_path))
    monkeypatch.setattr(
        script_module, "build_evaluation_bank", fake_build_evaluation_bank
    )
    monkeypatch.chdir(tmp_path / "elsewhere")
    monkeypatch.setattr(
        sys,
        "argv",
        ["build_evaluation_bank.py", "--input", ".local/evaluation/domains"],
    )

    assert script_module.main() == 0
    assert captured["repository_root"] == repository_root
    assert (
        captured["output_path"]
        == repository_root / ".local" / "evaluation" / "evaluation_bank.json"
    )


def test_tracked_evaluation_bank_is_encrypted_and_opaque() -> None:
    encrypted_path = Path(__file__).resolve().parents[1] / "evaluation_bank.json.cms"
    encrypted = encrypted_path.read_bytes()

    assert len(encrypted) > 100_000
    assert not encrypted.startswith(b"{")
    for forbidden in (b"BIL-EVAL", b"reference", b"required_points"):
        assert forbidden not in encrypted


def cast_reference(
    payloads: list[JsonDict], domain_index: int, case_index: int
) -> JsonDict:
    reference = cast_case(payloads, domain_index, case_index)["reference"]
    assert isinstance(reference, dict)
    return cast(JsonDict, reference)


def cast_rubric(
    payloads: list[JsonDict], domain_index: int, case_index: int
) -> JsonDict:
    rubric = cast_case(payloads, domain_index, case_index)["rubric"]
    assert isinstance(rubric, dict)
    return cast(JsonDict, rubric)


def cast_case(payloads: list[JsonDict], domain_index: int, case_index: int) -> JsonDict:
    cases = payloads[domain_index]["cases"]
    assert isinstance(cases, list)
    typed_cases = cast(list[JsonDict], cases)
    case = typed_cases[case_index]
    assert isinstance(case, dict)
    return case


def load_script_module():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "build_evaluation_bank.py"
    )
    spec = importlib.util.spec_from_file_location(
        "build_evaluation_bank_script", script_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
