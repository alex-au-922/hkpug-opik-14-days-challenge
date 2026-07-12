from __future__ import annotations

import re
from pathlib import Path

from hkpug_challenge.pr_validation import ALLOWED_SUBMISSION_PATHS


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_ROOT = REPO_ROOT / ".github" / "workflows"
VALIDATE_WORKFLOW = "validate-submission.yml"
TRUSTED_WORKFLOW = "trusted-score.yml"
PAGES_WORKFLOW = "deploy-pages.yml"
SUBMISSION_PATHS = {
    "submission/manifest.json",
    "submission/manifest.sig",
    "submission/prompt.txt.cms",
}


def load_workflow(filename: str) -> str:
    path = WORKFLOW_ROOT / filename
    assert path.is_file(), f"Missing required workflow: {path.relative_to(REPO_ROOT)}"
    return path.read_text(encoding="utf-8")


def top_level_block(text: str, key: str) -> str:
    lines = text.splitlines()
    marker = f"{key}:"
    try:
        start = next(index for index, line in enumerate(lines) if line == marker)
    except StopIteration:
        raise AssertionError(f"Workflow is missing top-level {marker}") from None

    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line and not line[0].isspace() and not line.startswith("#"):
            end = index
            break
    return "\n".join(lines[start:end])


def named_step(text: str, name_pattern: str) -> str:
    step_starts = [
        match.start()
        for match in re.finditer(r"(?m)^[ \t]*-[ \t]+name:[ \t]*.+$", text)
    ]
    for position, start in enumerate(step_starts):
        end = (
            step_starts[position + 1] if position + 1 < len(step_starts) else len(text)
        )
        block = text[start:end]
        first_line = block.splitlines()[0]
        if re.search(name_pattern, first_line, flags=re.IGNORECASE):
            return block
    raise AssertionError(f"Workflow is missing a step named like {name_pattern!r}")


def checkout_steps(text: str) -> tuple[str, ...]:
    step_starts = [
        match.start()
        for match in re.finditer(r"(?m)^[ \t]*-[ \t]+name:[ \t]*.+$", text)
    ]
    blocks: list[str] = []
    for position, start in enumerate(step_starts):
        end = (
            step_starts[position + 1] if position + 1 < len(step_starts) else len(text)
        )
        block = text[start:end]
        if "uses: actions/checkout@" in block:
            blocks.append(block)
    return tuple(blocks)


def submission_paths(text: str) -> set[str]:
    return set(re.findall(r"submission/[A-Za-z0-9_./*?-]+", text))


def assert_exact_submission_paths(text: str) -> None:
    assert submission_paths(text) == SUBMISSION_PATHS
    assert "submission/*" not in text
    assert "submission/**" not in text


def assert_action_references_are_pinned(text: str) -> None:
    references = re.findall(r"(?m)^\s*uses:\s*['\"]?([^'\"\s]+)", text)
    assert references, "Workflow must use at least one action"
    for reference in references:
        assert re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", reference), (
            f"Action must be pinned to a full commit SHA: {reference}"
        )


def permission_entries(text: str) -> dict[str, str]:
    block = top_level_block(text, "permissions")
    entries = dict(re.findall(r"(?m)^\s+([a-z-]+):\s*(read|write|none)\s*$", block))
    assert entries, "Use an explicit top-level permissions map"
    assert "write-all" not in block
    assert "read-all" not in block
    return entries


def assert_concurrency(
    text: str,
    *,
    group_pattern: str,
    cancel_in_progress: bool,
) -> None:
    block = top_level_block(text, "concurrency")
    assert re.search(group_pattern, block, flags=re.IGNORECASE)
    expected = str(cancel_in_progress).lower()
    assert re.search(
        rf"(?m)^\s+cancel-in-progress:\s*{expected}\s*$",
        block,
    )


def workflow_name(text: str) -> str:
    match = re.search(r"(?m)^name:\s*([^#\n]+?)\s*$", text)
    assert match is not None, "Workflow must have a stable name"
    return match.group(1).strip("'\"")


def test_required_two_stage_and_pages_workflows_exist() -> None:
    for filename in (VALIDATE_WORKFLOW, TRUSTED_WORKFLOW, PAGES_WORKFLOW):
        load_workflow(filename)


def test_all_reusable_actions_are_commit_sha_pinned() -> None:
    for filename in (VALIDATE_WORKFLOW, TRUSTED_WORKFLOW, PAGES_WORKFLOW):
        assert_action_references_are_pinned(load_workflow(filename))


def test_untrusted_validation_has_no_secrets_or_write_permissions() -> None:
    text = load_workflow(VALIDATE_WORKFLOW)
    trigger = top_level_block(text, "on")

    assert re.search(r"(?m)^\s+pull_request:\s*$", trigger)
    assert re.search(r"(?m)^\s+branches:\s*\[?main\]?\s*$", trigger)
    assert "pull_request_target:" not in trigger
    assert "workflow_run:" not in trigger
    assert "workflow_dispatch:" not in trigger
    assert "secrets." not in text
    assert permission_entries(text) == {
        "contents": "read",
        "pull-requests": "read",
    }
    assert_concurrency(
        text,
        group_pattern=r"group:.*pull_request\.number",
        cancel_in_progress=True,
    )


def test_untrusted_validation_runs_trusted_base_code_only() -> None:
    text = load_workflow(VALIDATE_WORKFLOW)
    checkouts = checkout_steps(text)

    assert checkouts, "Validation needs an explicit checkout of trusted base code"
    trusted_step = named_step(text, r"check out.*trusted.*base.*code")
    assert "github.event.pull_request.base.sha" in trusted_step
    assert "github.event.pull_request.head" not in trusted_step
    assert re.search(r"(?m)^\s+persist-credentials:\s*false\s*$", trusted_step)

    participant_checkouts = [
        step for step in checkouts if "github.event.pull_request.head.sha" in step
    ]
    for step in participant_checkouts:
        assert "github.event.pull_request.head.repo.full_name" in step
        assert "sparse-checkout:" in step
        assert "sparse-checkout-cone-mode: false" in step
        assert submission_paths(step) == SUBMISSION_PATHS
        assert re.search(r"(?m)^\s+persist-credentials:\s*false\s*$", step)
    assert not re.search(r"working-directory:\s*(?:\./)?untrusted(?:/|\s|$)", text)
    assert not re.search(r"(?m)^\s*(?:bash|sh|source)\s+[^\n]*untrusted", text)
    assert "uses: ./" not in text


def test_untrusted_validation_checks_exact_paths_and_signed_envelope() -> None:
    text = load_workflow(VALIDATE_WORKFLOW)
    assert set(ALLOWED_SUBMISSION_PATHS) == SUBMISSION_PATHS

    path_step = named_step(text, r"(?:validate|verify).*(?:changed )?paths")
    assert "scripts/validate_pr_files.py" in path_step
    assert "github.event.pull_request.head.sha" in path_step
    assert "github.event.pull_request.head.repo.full_name" in path_step

    envelope_step = named_step(
        text,
        r"(?:validate|verify).*(?:encrypted|signed).*envelope",
    )
    assert (
        "validate_submission" in envelope_step or "validate-envelope" in envelope_step
    )
    assert "SCORER_PRIVATE_KEY" not in envelope_step


def test_trusted_scoring_accepts_only_a_successful_expected_pr_workflow() -> None:
    validate_text = load_workflow(VALIDATE_WORKFLOW)
    text = load_workflow(TRUSTED_WORKFLOW)
    trigger = top_level_block(text, "on")
    expected_name = re.escape(workflow_name(validate_text))

    assert re.search(r"(?m)^\s+workflow_run:\s*$", trigger)
    assert re.search(rf"workflows:.*['\"]?{expected_name}['\"]?", trigger)
    assert re.search(r"types:\s*\[?completed\]?", trigger)
    assert "pull_request:" not in trigger
    assert "pull_request_target:" not in trigger
    assert permission_entries(text) == {
        "actions": "read",
        "contents": "write",
        "pull-requests": "write",
    }

    provenance = named_step(text, r"validate.*(?:workflow|run).*provenance")
    for token in (
        "github.event.workflow_run.id",
        "github.event.workflow_run.conclusion",
        "github.event.workflow_run.event",
        "github.event.workflow_run.repository.full_name",
        "github.event.workflow_run.head_repository.full_name",
        "github.event.workflow_run.head_sha",
        "github.repository",
        "base.ref",
        "head.repo.full_name",
        "head.sha",
        "main",
        "pull_request",
        "success",
    ):
        assert token in provenance
    assert "gh api" in provenance or "github.rest." in provenance


def test_trusted_refetches_immutable_blobs_without_pr_checkout() -> None:
    text = load_workflow(TRUSTED_WORKFLOW)
    assert_exact_submission_paths(text)
    assert "actions/download-artifact@" not in text

    checkouts = checkout_steps(text)
    assert checkouts, "Trusted scoring must explicitly checkout its trusted code"
    for step in checkouts:
        assert "ref: ${{ github.sha }}" in step
        assert "workflow_run.head_sha" not in step
        assert "pull_request.head" not in step
        assert re.search(r"(?m)^\s+persist-credentials:\s*false\s*$", step)

    fetch_step = named_step(
        text, r"(?:re-?fetch|download).*exact.*(?:submission )?blobs"
    )
    assert submission_paths(fetch_step) == SUBMISSION_PATHS
    assert "github.event.workflow_run.head_sha" in fetch_step
    assert "github.event.workflow_run.head_repository.full_name" in fetch_step
    assert "gh api" in fetch_step or "github.rest.repos.getContent" in fetch_step
    assert "git checkout" not in fetch_step
    assert "git clone" not in fetch_step
    assert "git fetch" not in fetch_step

    path_step = named_step(text, r"re-?validate.*exact.*(?:changed )?paths")
    assert "scripts/validate_pr_files.py" in path_step
    assert "github.event.workflow_run.head_sha" in path_step
    assert "github.event.workflow_run.head_repository.full_name" in path_step

    verify_step = named_step(text, r"re-?validate.*signed.*envelope")
    assert "scripts/verify_submission.py" in verify_step


def test_trusted_scoring_gates_secrets_and_atomically_reserves_eight_attempts() -> None:
    text = load_workflow(TRUSTED_WORKFLOW)
    secret_names = set(re.findall(r"secrets\.([A-Z0-9_]+)", text))

    assert secret_names - {"GITHUB_TOKEN"} == {
        "FIREWORKS_API_KEY",
        "SCORER_PRIVATE_KEY_PEM",
    }
    gate_step = named_step(text, r"(?:check|require|gate).*scoring.*enabled")
    assert re.search(
        r"vars\.SCORING_ENABLED\s*==\s*['\"]true['\"]",
        gate_step,
    )
    assert re.search(
        r"(?m)^\s+MAX_ATTEMPTS:\s*\$\{\{\s*vars\.MAX_ATTEMPTS\s*}}\s*$",
        text,
    )
    assert_concurrency(
        text,
        group_pattern=r"group:\s*(?:tournament-)?(?:score|scoring|attempt)[a-z-]*\s*$",
        cancel_in_progress=False,
    )

    reserve_step = named_step(
        text, r"reserve.*attempt.*atomic|atomic.*reserve.*attempt"
    )
    assert "MAX_ATTEMPTS" in reserve_step
    assert re.search(r"(?:==|=|-eq)\s*['\"]?8['\"]?", reserve_step)
    assert "workflow_run.head_sha" in reserve_step
    assert "prompt_sha256" in reserve_step
    assert "submission" in reserve_step.lower()

    score_step = named_step(text, r"score.*(?:fixed )?(?:evaluation )?bank")
    assert text.index(gate_step) < text.index(reserve_step) < text.index(score_step)


def test_trusted_feedback_is_encrypted_and_holdout_is_aggregate_only() -> None:
    text = load_workflow(TRUSTED_WORKFLOW)
    score_step = named_step(text, r"score.*(?:fixed )?(?:evaluation )?bank")
    encrypt_step = named_step(text, r"encrypt.*discovery.*feedback")
    upload_step = named_step(text, r"upload.*encrypted.*feedback")

    assert re.search(
        r"discovery(?:_|-|\s)+(?:feedback|output|mode).*?(?:full|trace)",
        score_step,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert re.search(
        r"holdout(?:_|-|\s)+(?:feedback|output|mode).*?aggregate(?:_|-|\s)*only",
        score_step,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert "scripts/encrypt_feedback.sh" in encrypt_step
    assert text.index(score_step) < text.index(encrypt_step) < text.index(upload_step)
    assert "actions/upload-artifact@" in upload_step
    assert re.search(r"(?m)^\s+path:\s*[^\n]*\.cms\s*$", upload_step)
    assert "retention-days: ${{ vars.BUNDLE_RETENTION_DAYS }}" in upload_step
    assert "if-no-files-found: error" in upload_step
    for forbidden in (
        "trace_payload.json",
        "span_payload.json",
        "evaluation_bank.json",
        "prompt.txt",
    ):
        assert forbidden not in upload_step


def test_leaderboard_update_is_serialized_append_only_and_non_force() -> None:
    text = load_workflow(TRUSTED_WORKFLOW)
    update_step = named_step(text, r"update.*leaderboard")

    assert "LEADERBOARD_BRANCH: ${{ vars.LEADERBOARD_BRANCH }}" in text
    assert "append" in update_step.lower()
    assert "git push" in update_step
    assert "LEADERBOARD_BRANCH" in update_step
    assert "--force" not in update_step
    assert not re.search(r"\bgit\s+push\s+-[^\n]*f", update_step)
    assert not re.search(r"git\s+push[^\n]*\+HEAD", update_step)
    assert "prompt" not in update_step.lower()
    assert "evaluation_bank" not in update_step


def test_pages_deploys_only_the_leaderboard_with_minimal_permissions() -> None:
    text = load_workflow(PAGES_WORKFLOW)
    trigger = top_level_block(text, "on")

    assert re.search(r"(?m)^\s+push:\s*$", trigger)
    assert re.search(r"(?m)^\s+branches:\s*\[?leaderboard\]?\s*$", trigger)
    assert "pull_request:" not in trigger
    assert "workflow_run:" not in trigger
    assert "secrets." not in text
    assert permission_entries(text) == {
        "contents": "read",
        "id-token": "write",
        "pages": "write",
    }
    assert_concurrency(
        text,
        group_pattern=r"group:\s*pages\s*$",
        cancel_in_progress=False,
    )
    for action in (
        "actions/configure-pages@",
        "actions/upload-pages-artifact@",
        "actions/deploy-pages@",
    ):
        assert action in text
    assert re.search(r"(?m)^\s+name:\s*github-pages\s*$", text)
    assert "dashboard" in text
