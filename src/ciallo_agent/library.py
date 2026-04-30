from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


def _load_json(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        text = re.sub(r",\s*([}\]])", r"\1", text)
        return json.loads(text)


def _gate_types_from_ucf_items(ucf_items: list[dict]) -> tuple[str, ...]:
    logic_constraints = next(
        (item for item in ucf_items if item.get("collection") == "logic_constraints"),
        {},
    )
    return tuple(
        gate["type"]
        for gate in logic_constraints.get("available_gates", [])
        if isinstance(gate, dict) and "type" in gate
    )


def _resolve_library_roots(
    cello_root: Path,
    ucf_root: Path | None = None,
    input_root: Path | None = None,
    output_root: Path | None = None,
) -> tuple[Path, Path, Path]:
    if ucf_root and input_root and output_root:
        return ucf_root, input_root, output_root

    candidates = [
        (
            cello_root / "sample-input" / "ucf" / "files" / "v2" / "ucf",
            cello_root / "sample-input" / "ucf" / "files" / "v2" / "input",
            cello_root / "sample-input" / "ucf" / "files" / "v2" / "output",
        ),
        (
            cello_root / "sample-input" / "DNACompiler",
            cello_root / "sample-input" / "DNACompiler",
            cello_root / "sample-input" / "DNACompiler",
        ),
        (
            cello_root / "sample-input" / "ucf",
            cello_root / "sample-input" / "ucf",
            cello_root / "sample-input" / "ucf",
        ),
    ]

    for cand_ucf, cand_input, cand_output in candidates:
        if cand_ucf.exists() and cand_input.exists() and cand_output.exists():
            return cand_ucf, cand_input, cand_output

    searched = "\n".join(
        f"ucf={u}, input={i}, output={o}" for u, i, o in candidates
    )
    raise FileNotFoundError(
        f"Could not resolve Cello library roots under {cello_root}. Tried:\n{searched}"
    )


def _find_matching_file(root: Path, version: str, kind: str) -> Path | None:
    exact = list(root.rglob(f"{version}.{kind}.json"))
    if exact:
        return exact[0]

    exact_casefold = [
        p for p in root.rglob("*.json")
        if p.name.lower() == f"{version}.{kind}.json".lower()
    ]
    if exact_casefold:
        return exact_casefold[0]

    loose = [
        p for p in root.rglob("*.json")
        if version.lower() in p.name.lower() and kind.lower() in p.name.lower()
    ]
    if loose:
        return loose[0]

    return None


def _project_root_from_cello_root(cello_root: Path) -> Path:
    return cello_root.parent.parent


def _find_baseline_io_file(project_root: Path, version: str, kind: str) -> Path | None:
    baseline_root = project_root / "docs" / "examples" / "verified-official-baseline"
    candidate = baseline_root / f"{version}.{kind}.json"
    if candidate.exists():
        return candidate
    return None


@dataclass(frozen=True)
class LibraryRecord:
    version: str
    chassis: str
    organism: str
    input_file: Path
    output_file: Path
    ucf_file: Path
    sensors: tuple[str, ...]
    output_devices: tuple[str, ...]
    gate_types: tuple[str, ...]

    def summary_line(self) -> str:
        sensors = ", ".join(self.sensors)
        outputs = ", ".join(self.output_devices)
        gates = ", ".join(self.gate_types)
        return (
            f"{self.version} | chassis={self.chassis} | organism={self.organism} | "
            f"sensors=[{sensors}] | outputs=[{outputs}] | gates=[{gates}]"
        )

    @classmethod
    def from_files(
        cls,
        *,
        version: str,
        chassis: str,
        organism: str,
        input_file: Path,
        output_file: Path,
        ucf_file: Path,
    ) -> "LibraryRecord":
        input_items = _load_json(input_file)
        output_items = _load_json(output_file)
        ucf_items = _load_json(ucf_file)
        return cls(
            version=version,
            chassis=chassis,
            organism=organism,
            input_file=input_file,
            output_file=output_file,
            ucf_file=ucf_file,
            sensors=tuple(
                item["name"]
                for item in input_items
                if item.get("collection") == "input_sensors"
            ),
            output_devices=tuple(
                item["name"]
                for item in output_items
                if item.get("collection") == "output_devices"
            ),
            gate_types=_gate_types_from_ucf_items(ucf_items),
        )


class CelloLibraryIndex:
    def __init__(
        self,
        records: list[LibraryRecord],
        skipped_records: list[str] | None = None,
    ) -> None:
        self.records = records
        self.skipped_records = skipped_records or []

    @classmethod
    def from_repo(
        cls,
        cello_root: Path,
        ucf_root: Path | None = None,
        input_root: Path | None = None,
        output_root: Path | None = None,
    ) -> "CelloLibraryIndex":
        ucf_root, input_root, output_root = _resolve_library_roots(
            cello_root=cello_root,
            ucf_root=ucf_root,
            input_root=input_root,
            output_root=output_root,
        )

        project_root = _project_root_from_cello_root(cello_root)

        records: list[LibraryRecord] = []
        skipped_records: list[str] = []

        ucf_files = list(ucf_root.rglob("*.UCF.json"))
        if not ucf_files:
            ucf_files = [
                p for p in ucf_root.rglob("*.json")
                if "ucf" in p.name.lower()
            ]

        seen_versions: set[str] = set()

        for ucf_path in sorted(ucf_files):
            if ucf_path.name.endswith(".UCF.json"):
                version = ucf_path.name.removesuffix(".UCF.json")
            else:
                version = ucf_path.stem

            if version in seen_versions:
                continue
            seen_versions.add(version)

            chassis = ucf_path.parent.name

            input_path = _find_matching_file(input_root, version, "input")
            output_path = _find_matching_file(output_root, version, "output")

            if not input_path:
                input_path = _find_baseline_io_file(project_root, version, "input")

            if not output_path:
                output_path = _find_baseline_io_file(project_root, version, "output")

            try:
                ucf_items = _load_json(ucf_path)
            except json.JSONDecodeError as exc:
                skipped_records.append(f"{version}: invalid UCF JSON ({exc})")
                continue

            if not input_path or not output_path:
                skipped_records.append(
                    f"{version}: missing matching input/output files"
                )
                continue

            try:
                input_items = _load_json(input_path)
                output_items = _load_json(output_path)
            except json.JSONDecodeError as exc:
                skipped_records.append(f"{version}: invalid input/output JSON ({exc})")
                continue

            header = next(
                (item for item in ucf_items if item.get("collection") == "header"),
                {},
            )

            records.append(
                LibraryRecord(
                    version=version,
                    chassis=chassis,
                    organism=header.get("organism", chassis),
                    input_file=input_path,
                    output_file=output_path,
                    ucf_file=ucf_path,
                    sensors=tuple(
                        item["name"]
                        for item in input_items
                        if item.get("collection") == "input_sensors"
                    ),
                    output_devices=tuple(
                        item["name"]
                        for item in output_items
                        if item.get("collection") == "output_devices"
                    ),
                    gate_types=_gate_types_from_ucf_items(ucf_items),
                )
            )

        if not records:
            detail = "\n".join(skipped_records) if skipped_records else "No candidate records found."
            raise FileNotFoundError(
                f"No Cello v2 library records were found under {ucf_root}.\n{detail}"
            )

        return cls(records, skipped_records=skipped_records)

    def to_prompt_context(self) -> str:
        return "\n".join(record.summary_line() for record in self.records)

    def with_records(self, extra_records: Iterable[LibraryRecord]) -> "CelloLibraryIndex":
        return CelloLibraryIndex(
            records=[*list(extra_records), *self.records],
            skipped_records=list(self.skipped_records),
        )

    def choose_record(
        self,
        target_chassis: str | None,
        required_sensor_count: int = 1,
        preferred_sensors: Iterable[str] | None = None,
        preferred_output_device: str | None = None,
    ) -> LibraryRecord:
        candidates = self.records
        if target_chassis:
            needle = target_chassis.lower()
            matched = [
                record
                for record in candidates
                if needle in record.chassis.lower()
                or needle in record.version.lower()
                or needle in record.organism.lower()
            ]
            if matched:
                candidates = matched

        sensor_ready = [
            record for record in candidates if len(record.sensors) >= required_sensor_count
        ]
        if sensor_ready:
            candidates = sensor_ready

        preferred_sensor_list = [sensor for sensor in (preferred_sensors or []) if sensor]

        def _score(record: LibraryRecord) -> tuple[int, int, int, int, int, str]:
            missing_sensors = sum(
                1 for sensor_name in preferred_sensor_list if sensor_name not in record.sensors
            )
            matching_sensors = sum(
                1 for sensor_name in preferred_sensor_list if sensor_name in record.sensors
            )
            output_penalty = (
                0
                if not preferred_output_device or preferred_output_device in record.output_devices
                else 1
            )
            official_tiebreak = 0 if record.version == "Eco1C1G1T1" else 1
            sensor_count_gap = abs(len(record.sensors) - required_sensor_count)
            return (
                missing_sensors,
                output_penalty,
                -matching_sensors,
                official_tiebreak,
                sensor_count_gap,
                record.version,
            )

        return min(candidates, key=_score)

    def get_record(self, version: str) -> LibraryRecord:
        for record in self.records:
            if record.version == version:
                return record
        raise KeyError(f"Cello library version '{version}' was not found in the local index.")