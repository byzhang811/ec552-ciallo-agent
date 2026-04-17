from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


def _load_json(path: Path) -> list[dict]:
    with path.open() as handle:
        return json.load(handle)


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
    def from_repo(cls, cello_root: Path) -> "CelloLibraryIndex":
        ucf_root = cello_root / "sample-input" / "ucf" / "files" / "v2" / "ucf"
        input_root = cello_root / "sample-input" / "ucf" / "files" / "v2" / "input"
        output_root = cello_root / "sample-input" / "ucf" / "files" / "v2" / "output"

        records: list[LibraryRecord] = []
        skipped_records: list[str] = []
        for ucf_path in sorted(ucf_root.glob("*/*.UCF.json")):
            chassis = ucf_path.parent.name
            version = ucf_path.name.removesuffix(".UCF.json")
            input_path = input_root / chassis / f"{version}.input.json"
            output_path = output_root / chassis / f"{version}.output.json"
            if not input_path.exists() or not output_path.exists():
                skipped_records.append(f"{version}: missing matching input/output files")
                continue

            try:
                input_items = _load_json(input_path)
                output_items = _load_json(output_path)
                ucf_items = _load_json(ucf_path)
            except json.JSONDecodeError as exc:
                skipped_records.append(f"{version}: invalid JSON ({exc})")
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
            raise FileNotFoundError(
                f"No Cello v2 library records were found under {ucf_root}"
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
