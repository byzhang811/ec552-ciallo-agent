from __future__ import annotations

import json
import shutil
from pathlib import Path

from .library import CelloLibraryIndex, LibraryRecord
from .models import (
    CustomLibraryManifest,
    CustomLibrarySpec,
    CustomOutputDeviceDefinition,
    CustomSensorDefinition,
)


def _slugify(text: str) -> str:
    chars = [character.lower() if character.isalnum() else "_" for character in text]
    slug = "".join(chars).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "custom_library"


def _load_json(path: Path) -> list[dict]:
    with path.open() as handle:
        return json.load(handle)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n")


def load_custom_library_spec(path: Path) -> CustomLibrarySpec:
    return CustomLibrarySpec.model_validate_json(path.read_text())


def _normalize_sequence(sequence: str) -> str:
    cleaned = "".join(sequence.split()).upper()
    invalid = {character for character in cleaned if character not in {"A", "T", "G", "C"}}
    if invalid:
        joined = ", ".join(sorted(invalid))
        raise ValueError(f"DNA sequence contains invalid bases: {joined}")
    return cleaned


def _named_index(items: list[dict]) -> dict[tuple[str, str], dict]:
    return {
        (item["collection"], item["name"]): item
        for item in items
        if "collection" in item and "name" in item
    }


def _ensure_names_available(items: list[dict], proposed_names: list[tuple[str, str]]) -> None:
    existing = _named_index(items)
    duplicates = [
        f"{collection}:{name}"
        for collection, name in proposed_names
        if (collection, name) in existing
    ]
    if duplicates:
        joined = ", ".join(sorted(duplicates))
        raise ValueError(f"Custom library entries would collide with existing names: {joined}")


def _first_input_response_function(base_input_items: list[dict]) -> str:
    sensor_lookup = {
        item["name"]: item
        for item in base_input_items
        if item.get("collection") == "input_sensors"
    }
    model_lookup = {
        item["name"]: item
        for item in base_input_items
        if item.get("collection") == "models"
    }
    for sensor in sensor_lookup.values():
        model = model_lookup.get(sensor["model"])
        if model and "response_function" in model.get("functions", {}):
            return model["functions"]["response_function"]
    return "sensor_response"


def _first_output_model_functions(base_output_items: list[dict]) -> dict[str, str]:
    output_lookup = {
        item["name"]: item
        for item in base_output_items
        if item.get("collection") == "output_devices"
    }
    model_lookup = {
        item["name"]: item
        for item in base_output_items
        if item.get("collection") == "models"
    }
    for output_device in output_lookup.values():
        model = model_lookup.get(output_device["model"])
        if model and model.get("functions"):
            return dict(model["functions"])
    return {
        "response_function": "linear_response",
        "input_composition": "linear_input_composition",
    }


def _sensor_items(
    sensor: CustomSensorDefinition,
    *,
    response_function_name: str,
) -> list[dict]:
    model_name = f"{sensor.name}_model"
    structure_name = f"{sensor.name}_structure"
    parameters = [
        {
            "name": "ymax",
            "value": sensor.ymax,
            "description": "Maximal transcription",
        },
        {
            "name": "ymin",
            "value": sensor.ymin,
            "description": "Minimal transcription",
        },
    ]
    if sensor.alpha is not None:
        parameters.append(
            {
                "name": "alpha",
                "value": sensor.alpha,
                "description": "Tandem parameter",
            }
        )
    if sensor.beta is not None:
        parameters.append(
            {
                "name": "beta",
                "value": sensor.beta,
                "description": "Tandem parameter",
            }
        )

    return [
        {
            "collection": "input_sensors",
            "name": sensor.name,
            "model": model_name,
            "structure": structure_name,
        },
        {
            "collection": "models",
            "name": model_name,
            "functions": {
                "response_function": response_function_name,
            },
            "parameters": parameters,
        },
        {
            "collection": "structures",
            "name": structure_name,
            "outputs": [
                sensor.promoter_name,
            ],
        },
        {
            "collection": "parts",
            "type": "promoter",
            "name": sensor.promoter_name,
            "dnasequence": _normalize_sequence(sensor.promoter_sequence),
        },
    ]


def _output_items(
    output_device: CustomOutputDeviceDefinition,
    *,
    model_functions: dict[str, str],
) -> list[dict]:
    model_name = f"{output_device.name}_model"
    structure_name = f"{output_device.name}_structure"
    input_defs = [
        {
            "name": f"in{index}",
            "part_type": "promoter",
        }
        for index in range(1, output_device.input_count + 1)
    ]
    components = [f"#in{index}" for index in range(1, output_device.input_count + 1)]
    components.append(output_device.cassette_name)
    return [
        {
            "collection": "output_devices",
            "name": output_device.name,
            "model": model_name,
            "structure": structure_name,
        },
        {
            "collection": "models",
            "name": model_name,
            "functions": model_functions,
            "parameters": [
                {
                    "name": "unit_conversion",
                    "value": output_device.unit_conversion,
                }
            ],
        },
        {
            "collection": "structures",
            "name": structure_name,
            "inputs": input_defs,
            "devices": [
                {
                    "name": output_device.name,
                    "components": components,
                }
            ],
        },
        {
            "collection": "parts",
            "type": "cassette",
            "name": output_device.cassette_name,
            "dnasequence": _normalize_sequence(output_device.cassette_sequence),
        },
    ]


class CustomLibraryAuthor:
    def __init__(self, library: CelloLibraryIndex, cello_root: Path) -> None:
        self._library = library
        self._cello_root = cello_root

    def author(
        self,
        spec: CustomLibrarySpec,
        output_root: Path,
        *,
        ucf_file: Path | None = None,
    ) -> CustomLibraryManifest:
        record = self._library.get_record(spec.base_version)
        run_name = _slugify(spec.library_name)
        run_dir = output_root / run_name
        run_dir.mkdir(parents=True, exist_ok=True)

        base_input_items = _load_json(record.input_file)
        base_output_items = _load_json(record.output_file)
        response_function_name = _first_input_response_function(base_input_items)
        output_model_functions = _first_output_model_functions(base_output_items)

        custom_input_items: list[dict] = []
        custom_output_items: list[dict] = []
        for sensor in spec.custom_input_sensors:
            custom_input_items.extend(
                _sensor_items(sensor, response_function_name=response_function_name)
            )
        for output_device in spec.custom_output_devices:
            custom_output_items.extend(
                _output_items(output_device, model_functions=output_model_functions)
            )

        _ensure_names_available(
            base_input_items,
            [
                (item["collection"], item["name"])
                for item in custom_input_items
                if "name" in item
            ],
        )
        _ensure_names_available(
            base_output_items,
            [
                (item["collection"], item["name"])
                for item in custom_output_items
                if "name" in item
            ],
        )

        input_path = run_dir / f"{run_name}.input.json"
        output_path = run_dir / f"{run_name}.output.json"
        ucf_path = run_dir / f"{run_name}.UCF.json"
        summary_path = run_dir / "summary.md"
        spec_path = run_dir / "custom_library_spec.json"
        manifest_path = run_dir / "manifest.json"

        _write_json(input_path, base_input_items + custom_input_items)
        _write_json(output_path, base_output_items + custom_output_items)
        source_ucf = ucf_file or record.ucf_file
        shutil.copy2(source_ucf, ucf_path)
        _write_json(spec_path, json.loads(spec.model_dump_json(indent=2)))

        warnings: list[str] = []
        if spec.custom_input_sensors:
            warnings.append(
                "Custom input sensors were appended to the base input sensor file."
            )
        if spec.custom_output_devices:
            warnings.append(
                "Custom output devices were appended to the base output device file."
            )
        if ucf_file is not None:
            warnings.append(
                "The UCF file was generated from a draft merge and may still need curation."
            )
        else:
            warnings.append(
                "The UCF file is still copied from the base official library; custom gate libraries are not generated yet."
            )

        summary_path.write_text(self._build_summary(spec, record, warnings))
        manifest = CustomLibraryManifest(
            library_name=spec.library_name,
            run_directory=str(run_dir),
            base_library_version=record.version,
            base_library_chassis=record.chassis,
            input_file=str(input_path),
            output_file=str(output_path),
            ucf_file=str(ucf_path),
            summary_file=str(summary_path),
            spec_file=str(spec_path),
            warnings=warnings,
        )
        _write_json(manifest_path, json.loads(manifest.model_dump_json(indent=2)))
        return manifest

    def _build_summary(
        self,
        spec: CustomLibrarySpec,
        record: LibraryRecord,
        warnings: list[str],
    ) -> str:
        sensor_lines = (
            "\n".join(
                f"- {sensor.name}: promoter={sensor.promoter_name}"
                for sensor in spec.custom_input_sensors
            )
            or "- None"
        )
        output_lines = (
            "\n".join(
                f"- {output.name}: cassette={output.cassette_name}, inputs={output.input_count}"
                for output in spec.custom_output_devices
            )
            or "- None"
        )
        note_lines = "\n".join(f"- {note}" for note in spec.notes) or "- None"
        warning_lines = "\n".join(f"- {warning}" for warning in warnings)
        return (
            f"# {spec.library_name}\n\n"
            "## Base Library\n\n"
            f"- Version: {record.version}\n"
            f"- Chassis: {record.chassis}\n"
            f"- Organism: {record.organism}\n\n"
            "## Custom Input Sensors\n\n"
            f"{sensor_lines}\n\n"
            "## Custom Output Devices\n\n"
            f"{output_lines}\n\n"
            "## Notes\n\n"
            f"{note_lines}\n\n"
            "## Warnings\n\n"
            f"{warning_lines}\n"
        )


def build_library_record_from_manifest(
    manifest: CustomLibraryManifest,
    library: CelloLibraryIndex,
) -> LibraryRecord:
    base_record = library.get_record(manifest.base_library_version)
    version = Path(manifest.run_directory).name
    return LibraryRecord.from_files(
        version=version,
        chassis=base_record.chassis,
        organism=base_record.organism,
        input_file=Path(manifest.input_file),
        output_file=Path(manifest.output_file),
        ucf_file=Path(manifest.ucf_file),
    )
