from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, cast


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_onboarding_bundle.py"
PROJECT_NAME = "HKPUG Mini Workshop Onboarding"
ARCHIVE_ROOT = "hkpug-opik-mini-workshop-onboarding"


def test_builder_packages_the_existing_six_case_workshop(tmp_path: Path) -> None:
    output = tmp_path / "onboarding.zip"

    subprocess.run([sys.executable, str(BUILDER), "--output", str(output)], check=True)
    first_bytes = output.read_bytes()
    subprocess.run([sys.executable, str(BUILDER), "--output", str(output)], check=True)

    assert output.read_bytes() == first_bytes
    assert output.with_suffix(".zip.sha256").is_file()

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert f"{ARCHIVE_ROOT}/README.md" in names
        assert f"{ARCHIVE_ROOT}/questions.md" in names
        assert f"{ARCHIVE_ROOT}/answers.json" in names
        assert f"{ARCHIVE_ROOT}/code/shared/fixtures.py" in names
        assert f"{ARCHIVE_ROOT}/code/cases/case_006_release_gate.py" in names

        run = _read_json(archive, "opik/run.json")
        traces = _read_json(archive, "opik/trace_payload.json")["traces"]
        spans = _read_json(archive, "opik/span_payload.json")["spans"]
        native = _read_json(archive, "opik/native_features.json")
        answers = _read_json(archive, "answers.json")

    assert run["schema_version"] == 1
    assert run["bundle_partition"] == "discovery"
    assert run["project_name"] == PROJECT_NAME
    assert run["holdout"] == {"case_count": 0, "criteria": {}, "score": 0.0}
    assert len(traces) == 6
    assert len(spans) == 43
    assert all(item["metadata"]["partition"] == "discovery" for item in traces)
    assert all(item["metadata"]["partition"] == "discovery" for item in spans)
    assert all(item["project_name"] == PROJECT_NAME for item in traces)
    assert all(item["project_name"] == PROJECT_NAME for item in spans)
    assert len(native["dataset"]["items"]) == 6
    assert len(native["experiments"]) == 2
    assert all(len(experiment["items"]) == 6 for experiment in native["experiments"])
    assert set(answers) == {"001", "002", "003", "004", "005", "006"}


def _read_json(archive: zipfile.ZipFile, relative_path: str) -> dict[str, Any]:
    payload = json.loads(archive.read(f"{ARCHIVE_ROOT}/{relative_path}"))
    assert isinstance(payload, dict)
    return cast(dict[str, Any], payload)
