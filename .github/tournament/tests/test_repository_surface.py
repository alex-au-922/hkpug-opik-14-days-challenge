from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / ".git").exists()
)


def test_repository_root_contains_only_participant_surfaces() -> None:
    visible_entries = {
        path.name
        for path in REPOSITORY_ROOT.iterdir()
        if path.name in {".github", ".gitignore"} or not path.name.startswith(".")
    }

    assert visible_entries == {
        ".github",
        ".gitignore",
        "README.md",
        "public",
        "starter",
        "submission",
    }


def test_embedded_organizer_certificate_matches_tracked_public_certificate() -> None:
    embedded = (
        REPOSITORY_ROOT
        / ".github"
        / "tournament"
        / "helper"
        / "cmd"
        / "hkpug-opik-helper"
        / "scorer_cert.pem"
    )
    tracked = (
        REPOSITORY_ROOT / ".github" / "tournament" / "public_keys" / "scorer_cert.pem"
    )

    assert embedded.read_bytes() == tracked.read_bytes()


def test_readme_is_participant_facing() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

    for required in (
        "Opik 14-Day Challenge",
        "eight",
        "hkpug-opik-helper",
        "submission.zip",
        "pull request",
        "encrypted feedback",
        "Opik",
    ):
        assert required.lower() in readme.lower()
    for forbidden in (
        "maintainer",
        "internal",
        "trusted scorer code",
        "local checks",
        "encrypt_prompt.sh",
        "uv run",
    ):
        assert forbidden not in readme.lower()
