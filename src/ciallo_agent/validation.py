from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from .models import ArtifactManifest


def _load_json(path: Path) -> object:
    with path.open() as handle:
        return json.load(handle)


def _validate_json_against_schema(
    payload_path: Path,
    schema_path: Path,
    schema_root: Path,
) -> None:
    schema = _load_json(schema_path)
    resolver = jsonschema.RefResolver(f"file://{schema_root}/", "")
    validator = jsonschema.Draft7Validator(schema, resolver=resolver)
    validator.validate(_load_json(payload_path))


def validate_bundle(manifest: ArtifactManifest, cello_root: Path) -> list[str]:
    return validate_file_triplet(
        input_path=Path(manifest.input_file),
        output_path=Path(manifest.output_file),
        ucf_path=Path(manifest.ucf_file),
        cello_root=cello_root,
        selected_sensors=manifest.selected_sensors,
        selected_output_device=manifest.selected_output_device,
    )


def validate_file_triplet(
    *,
    input_path: Path,
    output_path: Path,
    ucf_path: Path,
    cello_root: Path,
    selected_sensors: list[str] | None = None,
    selected_output_device: str | None = None,
) -> list[str]:
    issues: list[str] = []
    schemas_root = cello_root / "sample-input" / "ucf" / "schemas" / "v2"
    checks = (
        ("input file", input_path, schemas_root / "input_sensor_file.schema.json"),
        ("output file", output_path, schemas_root / "output_device_file.schema.json"),
        ("UCF file", ucf_path, schemas_root / "ucf.schema.json"),
    )

    for label, payload_path, schema_path in checks:
        try:
            _validate_json_against_schema(payload_path, schema_path, schemas_root)
        except Exception as exc:  # noqa: BLE001
            issues.append(f"{label} failed schema validation: {exc}")

    try:
        input_items = _load_json(input_path)
        input_sensor_names = {
            item["name"]
            for item in input_items
            if isinstance(item, dict) and item.get("collection") == "input_sensors"
        }
        missing_sensors = sorted(set(selected_sensors or []) - input_sensor_names)
        if missing_sensors:
            issues.append(
                f"Selected sensors missing from generated input file: {', '.join(missing_sensors)}"
            )
    except Exception as exc:  # noqa: BLE001
        issues.append(f"Failed to inspect generated input file: {exc}")

    try:
        output_items = _load_json(output_path)
        output_device_names = {
            item["name"]
            for item in output_items
            if isinstance(item, dict) and item.get("collection") == "output_devices"
        }
        if (
            selected_output_device
            and selected_output_device not in output_device_names
        ):
            issues.append(
                f"Selected output device missing from generated output file: {selected_output_device}"
            )
    except Exception as exc:  # noqa: BLE001
        issues.append(f"Failed to inspect generated output file: {exc}")

    return issues
