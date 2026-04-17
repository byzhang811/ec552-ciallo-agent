from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Iterable

from .library import CelloLibraryIndex, LibraryRecord
from .models import ArtifactManifest, DesignSpec


def _slugify(text: str) -> str:
    chars = [character.lower() if character.isalnum() else "_" for character in text]
    slug = "".join(chars).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "design_run"


def _load_json(path: Path) -> list[dict]:
    with path.open() as handle:
        return json.load(handle)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _by_collection_and_name(items: Iterable[dict]) -> dict[tuple[str, str], dict]:
    indexed: dict[tuple[str, str], dict] = {}
    for item in items:
        collection = item.get("collection")
        name = item.get("name")
        if collection and name:
            indexed[(collection, name)] = item
    return indexed


def _preserve_order(items: list[dict], wanted: dict[str, set[str]]) -> list[dict]:
    selected = []
    for item in items:
        collection = item.get("collection")
        name = item.get("name")
        if collection in wanted and name in wanted[collection]:
            selected.append(item)
    return selected


def _filter_input_items(items: list[dict], selected_sensors: list[str]) -> list[dict]:
    wanted: dict[str, set[str]] = {
        "input_sensors": set(selected_sensors),
        "models": set(),
        "structures": set(),
        "functions": set(),
        "parts": set(),
    }
    index = _by_collection_and_name(items)

    for sensor_name in selected_sensors:
        sensor = index.get(("input_sensors", sensor_name))
        if sensor is None:
            continue
        wanted["models"].add(sensor["model"])
        wanted["structures"].add(sensor["structure"])

    for model_name in list(wanted["models"]):
        model = index.get(("models", model_name))
        if model is None:
            continue
        wanted["functions"].update(model.get("functions", {}).values())

    for structure_name in list(wanted["structures"]):
        structure = index.get(("structures", structure_name))
        if structure is None:
            continue
        wanted["parts"].update(structure.get("outputs", []))

    return _preserve_order(items, wanted)


def _filter_output_items(items: list[dict], selected_output_device: str) -> list[dict]:
    wanted: dict[str, set[str]] = {
        "output_devices": {selected_output_device},
        "models": set(),
        "structures": set(),
        "functions": set(),
        "parts": set(),
    }
    index = _by_collection_and_name(items)

    device = index.get(("output_devices", selected_output_device))
    if device:
        wanted["models"].add(device["model"])
        wanted["structures"].add(device["structure"])

    for model_name in list(wanted["models"]):
        model = index.get(("models", model_name))
        if model is None:
            continue
        wanted["functions"].update(model.get("functions", {}).values())

    for structure_name in list(wanted["structures"]):
        structure = index.get(("structures", structure_name))
        if structure is None:
            continue
        for device_block in structure.get("devices", []):
            for component in device_block.get("components", []):
                if isinstance(component, str) and not component.startswith("#"):
                    wanted["parts"].add(component)

    return _preserve_order(items, wanted)


class ArtifactGenerator:
    def __init__(self, repo_root: Path, library: CelloLibraryIndex, cello_root: Path) -> None:
        self._repo_root = repo_root
        self._library = library
        self._cello_root = cello_root

    def generate_bundle(
        self,
        spec: DesignSpec,
        output_root: Path,
        library: CelloLibraryIndex | None = None,
    ) -> ArtifactManifest:
        output_root.mkdir(parents=True, exist_ok=True)
        active_library = library or self._library
        record = active_library.choose_record(
            spec.target_chassis,
            required_sensor_count=max(len(spec.inputs), 1),
            preferred_sensors=spec.selected_sensor_names,
            preferred_output_device=spec.selected_output_device_name,
        )
        run_name = _slugify(spec.design_name)
        run_dir = output_root / run_name
        run_dir.mkdir(parents=True, exist_ok=True)
        cello_output_dir = run_dir / "cello_output"
        cello_output_dir.mkdir(exist_ok=True)

        warnings: list[str] = []
        selected_sensors = self._resolve_sensors(spec, record, warnings)
        selected_output = self._resolve_output_device(spec, record, warnings)

        input_items = _load_json(record.input_file)
        output_items = _load_json(record.output_file)

        filtered_input = _filter_input_items(input_items, selected_sensors)
        filtered_output = _filter_output_items(output_items, selected_output)

        verilog_path = run_dir / f"{spec.verilog_module_name}.v"
        input_path = run_dir / f"{record.version}.input.json"
        output_path = run_dir / f"{record.version}.output.json"
        ucf_path = run_dir / f"{record.version}.UCF.json"
        options_path = run_dir / "options.csv"
        spec_path = run_dir / "design_spec.json"
        summary_path = run_dir / "summary.md"
        manifest_path = run_dir / "manifest.json"

        verilog_path.write_text(spec.verilog_code.strip() + "\n")
        _write_json(input_path, filtered_input)
        _write_json(output_path, filtered_output)
        shutil.copy2(record.ucf_file, ucf_path)
        shutil.copy2(
            self._cello_root / "sample-input" / "DNACompiler" / "primitives" / "options.csv",
            options_path,
        )
        _write_json(spec_path, json.loads(spec.model_dump_json(indent=2)))
        summary_path.write_text(self._build_summary(spec, record, selected_sensors, selected_output))

        if spec.custom_part_requests:
            _write_json(
                run_dir / "ucf_customization.todo.json",
                [
                    {
                        "name": request.name,
                        "part_type": request.part_type,
                        "reason": request.reason,
                        "sequence": request.sequence,
                        "source_hint": request.source_hint,
                    }
                    for request in spec.custom_part_requests
                ],
            )
            warnings.append(
                "Custom UCF requests were captured in ucf_customization.todo.json and still need manual curation."
            )

        manifest = ArtifactManifest(
            run_name=run_name,
            run_directory=str(run_dir),
            source_library_version=record.version,
            source_library_chassis=record.chassis,
            verilog_file=str(verilog_path),
            input_file=str(input_path),
            output_file=str(output_path),
            ucf_file=str(ucf_path),
            options_file=str(options_path),
            spec_file=str(spec_path),
            summary_file=str(summary_path),
            cello_output_dir=str(cello_output_dir),
            selected_sensors=selected_sensors,
            selected_output_device=selected_output,
            warnings=warnings,
        )
        _write_json(manifest_path, json.loads(manifest.model_dump_json(indent=2)))
        return manifest

    def _resolve_sensors(
        self,
        spec: DesignSpec,
        record: LibraryRecord,
        warnings: list[str],
    ) -> list[str]:
        required = max(len(spec.inputs), 1)
        selected = [
            sensor_name
            for sensor_name in spec.selected_sensor_names
            if sensor_name in record.sensors
        ]
        if len(selected) < len(spec.selected_sensor_names):
            warnings.append(
                "One or more preferred sensors were not present in the chosen library and were replaced."
            )
        for sensor_name in record.sensors:
            if sensor_name not in selected:
                selected.append(sensor_name)
            if len(selected) >= required:
                break
        return selected[:required]

    def _resolve_output_device(
        self,
        spec: DesignSpec,
        record: LibraryRecord,
        warnings: list[str],
    ) -> str:
        preferred = spec.selected_output_device_name
        if preferred and preferred in record.output_devices:
            return preferred
        if preferred:
            warnings.append(
                "Preferred output device was not available in the chosen library and was replaced."
            )
        return record.output_devices[0]

    def _build_summary(
        self,
        spec: DesignSpec,
        record: LibraryRecord,
        selected_sensors: list[str],
        selected_output: str,
    ) -> str:
        constraints = "\n".join(f"- {item}" for item in spec.constraints) or "- None"
        review_notes = "\n".join(f"- {item}" for item in spec.manual_review_notes) or "- None"
        validation_checks = (
            "\n".join(f"- {item}" for item in spec.validation_checks) or "- None"
        )
        return (
            f"# {spec.design_name}\n\n"
            "## Request Summary\n\n"
            f"{spec.summary}\n\n"
            "## Selected Official Library\n\n"
            f"- Version: {record.version}\n"
            f"- Chassis: {record.chassis}\n"
            f"- Organism: {record.organism}\n"
            f"- Sensors: {', '.join(selected_sensors)}\n"
            f"- Output device: {selected_output}\n\n"
            "## Logic\n\n"
            f"{spec.logic_description}\n\n"
            "## Constraints\n\n"
            f"{constraints}\n\n"
            "## Validation Checklist\n\n"
            f"{validation_checks}\n\n"
            "## Manual Review Notes\n\n"
            f"{review_notes}\n"
        )
