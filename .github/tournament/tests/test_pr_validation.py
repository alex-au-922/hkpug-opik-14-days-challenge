from __future__ import annotations

import pytest

from hkpug_challenge.pr_validation import ALLOWED_SUBMISSION_PATHS, validate_pr_files


def test_validate_pr_files_accepts_only_the_submission_archive() -> None:
    assert ALLOWED_SUBMISSION_PATHS == frozenset({"submission/submission.zip"})
    payload = [
        {"filename": path, "status": "modified"}
        for path in sorted(ALLOWED_SUBMISSION_PATHS)
    ]

    assert validate_pr_files(payload) == tuple(sorted(ALLOWED_SUBMISSION_PATHS))


@pytest.mark.parametrize(
    "payload",
    [
        [],
        [{"filename": "README.md", "status": "modified"}],
        [
            {"filename": path, "status": "modified"}
            for path in sorted(ALLOWED_SUBMISSION_PATHS)
        ]
        + [{"filename": "src/backdoor.py", "status": "added"}],
        [
            {"filename": path, "status": "removed"}
            for path in sorted(ALLOWED_SUBMISSION_PATHS)
        ],
        [
            {
                "filename": path,
                "status": "renamed",
                "previous_filename": "README.md",
            }
            for path in sorted(ALLOWED_SUBMISSION_PATHS)
        ],
    ],
)
def test_validate_pr_files_rejects_missing_extra_or_unsafe_changes(
    payload: object,
) -> None:
    with pytest.raises(ValueError):
        validate_pr_files(payload)
