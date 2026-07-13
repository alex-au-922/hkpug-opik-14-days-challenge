from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any, cast


TOURNAMENT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = TOURNAMENT_ROOT / "onboarding" / "mini-workshop"
OUTPUT_PATH = (
    TOURNAMENT_ROOT
    / "dashboard"
    / "tutorial"
    / "assets"
    / "hkpug-opik-mini-workshop-onboarding.zip"
)
ARCHIVE_ROOT = "hkpug-opik-mini-workshop-onboarding"
PROJECT_NAME = "HKPUG Mini Workshop Onboarding"
FIXED_TIMESTAMP = (2026, 7, 11, 0, 0, 0)


def build_bundle(source_root: Path, output_path: Path) -> str:
    files = _bundle_files(source_root)
    manifest = {
        "schema_version": 1,
        "project_name": PROJECT_NAME,
        "trace_count": 6,
        "files": {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in sorted(files.items())
        },
    }
    files["manifest.json"] = _encode_json(manifest)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for name, payload in sorted(files.items()):
            info = zipfile.ZipInfo(f"{ARCHIVE_ROOT}/{name}", FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payload)

    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    output_path.with_suffix(f"{output_path.suffix}.sha256").write_text(
        f"{digest}  {output_path.name}\n", encoding="ascii"
    )
    return digest


def _bundle_files(source_root: Path) -> dict[str, bytes]:
    opik_root = source_root / "opik"
    trace_payload = _prepare_collection(
        _load_object(opik_root / "trace_payload.json"), "traces"
    )
    span_payload = _prepare_collection(
        _load_object(opik_root / "span_payload.json"), "spans"
    )
    trace_feedback = _replace_project_names(
        _load_object(opik_root / "trace_feedback.json")
    )
    span_feedback = _replace_project_names(
        _load_object(opik_root / "span_feedback.json")
    )
    native_features = _replace_project_names(
        _load_object(opik_root / "native_features.json")
    )
    run = {
        "schema_version": 1,
        "bundle_partition": "discovery",
        "project_name": PROJECT_NAME,
        "onboarding": {"case_count": 6, "source": "HKPUG Opik Mini Workshop"},
        "holdout": {"case_count": 0, "criteria": {}, "score": 0.0},
    }

    files = {
        "README.md": _readme().encode(),
        "answers.json": (source_root / "answers.json").read_bytes(),
        "questions.md": (source_root / "questions.md").read_bytes(),
        "opik/run.json": _encode_json(run),
        "opik/trace_payload.json": _encode_json(trace_payload),
        "opik/span_payload.json": _encode_json(span_payload),
        "opik/trace_feedback.json": _encode_json(trace_feedback),
        "opik/span_feedback.json": _encode_json(span_feedback),
        "opik/native_features.json": _encode_json(native_features),
    }
    for path in sorted((source_root / "code").rglob("*.py")):
        files[f"code/{path.relative_to(source_root / 'code').as_posix()}"] = (
            path.read_bytes()
        )
    return files


def _prepare_collection(payload: dict[str, Any], collection: str) -> dict[str, Any]:
    items = payload.get(collection)
    if not isinstance(items, list):
        raise ValueError(f"{collection} payload must contain a list")
    prepared: list[dict[str, Any]] = []
    for raw_item in items:
        if not isinstance(raw_item, dict):
            raise ValueError(f"{collection} payload entries must be objects")
        item = cast(dict[str, Any], _replace_project_names(raw_item))
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            item["metadata"] = metadata
        cast(dict[str, Any], metadata)["partition"] = "discovery"
        prepared.append(item)
    return {collection: prepared}


def _replace_project_names(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: PROJECT_NAME if key == "project_name" else _replace_project_names(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_project_names(item) for item in value]
    return value


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return cast(dict[str, Any], payload)


def _encode_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _readme() -> str:
    return f"""# HKPUG Opik Mini Workshop Onboarding

This public bundle contains the existing six mini-workshop traces, span trees,
feedback scores, Dataset and Experiments data, Python case files, questions, and
answer key. It does not contain any hidden 14-day tournament cases.

## Load into local Opik

1. Start Opik and wait for http://localhost:5173 to become available.
2. Install the latest `hkpug-opik-helper` release.
3. From this extracted directory, run:

```sh
hkpug-opik-helper load \\
  --feedback opik \\
  --opik-url http://localhost:5173/api \\
  --workspace default
```

Open the `{PROJECT_NAME}` project, choose **Logs**, then **Traces**. Case 006
also uses the **Experiments** page.
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    digest = build_bundle(args.source, args.output)
    print(f"{digest}  {args.output}")


if __name__ == "__main__":
    main()
