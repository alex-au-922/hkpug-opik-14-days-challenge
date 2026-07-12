from __future__ import annotations

import io
import os
import stat
import tempfile
import zipfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from hkpug_challenge.submission_crypto import MAX_CIPHERTEXT_BYTES
from hkpug_challenge.submission_manifest import (
    MAX_MANIFEST_BYTES,
    MAX_SIGNATURE_BYTES,
    read_bounded_regular_file,
)


SUBMISSION_ARCHIVE_FILENAME = "submission.zip"
SUBMISSION_ARCHIVE_PATH = f"submission/{SUBMISSION_ARCHIVE_FILENAME}"
MAX_SUBMISSION_ARCHIVE_BYTES = 128 * 1024
EXPECTED_ARCHIVE_ENTRIES = {
    "manifest.json": MAX_MANIFEST_BYTES,
    "manifest.sig": MAX_SIGNATURE_BYTES,
    "prompt.txt.cms": MAX_CIPHERTEXT_BYTES,
}
_ALLOWED_COMPRESSION = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}


@contextmanager
def materialize_submission_archive(
    submission_archive: Path,
) -> Generator[Path, None, None]:
    archive_bytes = read_bounded_regular_file(
        submission_archive,
        "Submission archive",
        MAX_SUBMISSION_ARCHIVE_BYTES,
    )
    with tempfile.TemporaryDirectory(prefix="hkpug-submission-") as directory:
        destination = Path(directory)
        extract_submission_archive_bytes(archive_bytes, destination)
        yield destination


def extract_submission_archive(
    submission_archive: Path,
    destination: Path,
) -> tuple[Path, ...]:
    archive_bytes = read_bounded_regular_file(
        submission_archive,
        "Submission archive",
        MAX_SUBMISSION_ARCHIVE_BYTES,
    )
    return extract_submission_archive_bytes(archive_bytes, destination)


def extract_submission_archive_bytes(
    archive_bytes: bytes,
    destination: Path,
) -> tuple[Path, ...]:
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), mode="r") as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)):
                raise ValueError("Submission archive contains duplicate entries.")
            if set(names) != set(EXPECTED_ARCHIVE_ENTRIES):
                raise ValueError(
                    "Submission archive must contain exactly manifest.json, "
                    "manifest.sig, and prompt.txt.cms."
                )

            payloads: dict[str, bytes] = {}
            for entry in entries:
                _validate_archive_entry(entry)
                limit = EXPECTED_ARCHIVE_ENTRIES[entry.filename]
                with archive.open(entry, mode="r") as stream:
                    payload = stream.read(limit + 1)
                if len(payload) > limit:
                    raise ValueError(
                        f"Submission archive entry {entry.filename!r} is too large."
                    )
                payloads[entry.filename] = payload
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise ValueError("Submission archive is not a valid ZIP file.") from exc

    try:
        destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    except FileExistsError as exc:
        raise ValueError(
            "Submission archive destination must be a real directory."
        ) from exc
    if not stat.S_ISDIR(destination.lstat().st_mode):
        raise ValueError("Submission archive destination must be a real directory.")
    if any(destination.iterdir()):
        raise ValueError("Submission archive destination must be empty.")

    written: list[Path] = []
    for name in sorted(payloads):
        path = destination / name
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(payloads[name])
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        written.append(path)
    return tuple(written)


def _validate_archive_entry(entry: zipfile.ZipInfo) -> None:
    if entry.filename not in EXPECTED_ARCHIVE_ENTRIES:
        raise ValueError("Submission archive contains an unexpected entry.")
    if entry.is_dir() or entry.flag_bits & 0x1:
        raise ValueError("Submission archive entries must be unencrypted files.")
    if entry.compress_type not in _ALLOWED_COMPRESSION:
        raise ValueError("Submission archive uses an unsupported compression method.")
    if entry.file_size > EXPECTED_ARCHIVE_ENTRIES[entry.filename]:
        raise ValueError(f"Submission archive entry {entry.filename!r} is too large.")
    unix_mode = entry.external_attr >> 16
    if unix_mode and stat.S_IFMT(unix_mode) not in {0, stat.S_IFREG}:
        raise ValueError("Submission archive entries must be regular files.")
