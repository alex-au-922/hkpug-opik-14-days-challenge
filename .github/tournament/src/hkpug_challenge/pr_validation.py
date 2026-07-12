from __future__ import annotations

from typing import cast


ALLOWED_SUBMISSION_PATHS = frozenset(
    {
        "submission/submission.zip",
    }
)
ALLOWED_FILE_STATUSES = frozenset({"added", "modified"})


def validate_pr_files(payload: object) -> tuple[str, ...]:
    if not isinstance(payload, list):
        raise ValueError("Pull request files payload must be a JSON array.")

    observed: list[tuple[str, str]] = []
    for item_value in cast(list[object], payload):
        if not isinstance(item_value, dict):
            raise ValueError("Each pull request file must be one JSON object.")
        item = cast(dict[str, object], item_value)
        filename = item.get("filename")
        status = item.get("status")
        if not isinstance(filename, str) or not isinstance(status, str):
            raise ValueError("Pull request file entries require filename and status.")
        observed.append((filename, status))

    filenames = [filename for filename, _status in observed]
    if len(filenames) != len(set(filenames)):
        raise ValueError("Pull request file list contains duplicate paths.")
    if set(filenames) != set(ALLOWED_SUBMISSION_PATHS):
        raise ValueError(
            "Submission pull requests must change exactly submission/submission.zip."
        )
    unsafe_statuses = sorted(
        {status for _filename, status in observed} - ALLOWED_FILE_STATUSES
    )
    if unsafe_statuses:
        raise ValueError(
            "Submission files must be added or modified, not "
            + ", ".join(unsafe_statuses)
            + "."
        )
    return tuple(sorted(filenames))
