from __future__ import annotations

import json
import hashlib
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from .models import (
    FieldOrigin,
    PaperGateCandidate,
    PaperOutputDeviceCandidate,
    PaperSensorCandidate,
    PaperUCFDraft,
    UCFParameter,
)


ORIGIN_RANK: dict[FieldOrigin, int] = {
    "extracted": 3,
    "inferred": 2,
    "defaulted": 1,
    "missing": 0,
}


def dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        stripped = value.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        ordered.append(stripped)
    return ordered


def _safe_name(text: str, fallback: str) -> str:
    chars = [character if character.isalnum() else "_" for character in text.strip()]
    slug = "".join(chars).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or fallback


def _better_origin(left: FieldOrigin, right: FieldOrigin) -> bool:
    return ORIGIN_RANK[left] >= ORIGIN_RANK[right]


def _pick_text(*values: str | None) -> str | None:
    for value in values:
        if value and value.strip():
            return value
    return None


def _pick_by_status(
    left_value: str | None,
    left_status: FieldOrigin,
    right_value: str | None,
    right_status: FieldOrigin,
) -> tuple[str | None, FieldOrigin]:
    if _better_origin(left_status, right_status):
        return (left_value if left_value else right_value, left_status)
    return (right_value if right_value else left_value, right_status)


def merge_parameters(parameters: list[UCFParameter]) -> list[UCFParameter]:
    merged: dict[str, UCFParameter] = {}
    for parameter in parameters:
        key = parameter.name.lower()
        current = merged.get(key)
        if current is None or ORIGIN_RANK[parameter.status] > ORIGIN_RANK[current.status]:
            merged[key] = parameter
        elif current is not None and current.value is None and parameter.value is not None:
            merged[key] = parameter
    return list(merged.values())


def merge_sensor_candidates(candidates: list[PaperSensorCandidate]) -> list[PaperSensorCandidate]:
    merged: dict[str, PaperSensorCandidate] = {}
    for candidate in candidates:
        key = candidate.name
        current = merged.get(key)
        if current is None:
            merged[key] = candidate
            continue
        promoter_sequence, promoter_status = _pick_by_status(
            current.promoter_sequence,
            current.promoter_sequence_status,
            candidate.promoter_sequence,
            candidate.promoter_sequence_status,
        )
        merged[key] = PaperSensorCandidate(
            name=current.name,
            inducer=_pick_text(current.inducer, candidate.inducer),
            promoter_name=_pick_text(current.promoter_name, candidate.promoter_name) or current.promoter_name,
            promoter_sequence=promoter_sequence,
            promoter_sequence_status=promoter_status,
            response_function=_pick_text(candidate.response_function, current.response_function) or "sensor_response",
            parameters=merge_parameters([*current.parameters, *candidate.parameters]),
            evidence=dedupe_strings([*current.evidence, *candidate.evidence]),
        )
    return list(merged.values())


def merge_output_candidates(
    candidates: list[PaperOutputDeviceCandidate],
) -> list[PaperOutputDeviceCandidate]:
    merged: dict[str, PaperOutputDeviceCandidate] = {}
    for candidate in candidates:
        key = candidate.name
        current = merged.get(key)
        if current is None:
            merged[key] = candidate
            continue
        cassette_sequence, cassette_status = _pick_by_status(
            current.cassette_sequence,
            current.cassette_sequence_status,
            candidate.cassette_sequence,
            candidate.cassette_sequence_status,
        )
        unit_conversion = (
            current.unit_conversion
            if _better_origin(current.unit_conversion_status, candidate.unit_conversion_status)
            else candidate.unit_conversion
        )
        unit_status = (
            current.unit_conversion_status
            if _better_origin(current.unit_conversion_status, candidate.unit_conversion_status)
            else candidate.unit_conversion_status
        )
        merged[key] = PaperOutputDeviceCandidate(
            name=current.name,
            reporter=_pick_text(current.reporter, candidate.reporter),
            cassette_name=_pick_text(current.cassette_name, candidate.cassette_name) or current.cassette_name,
            cassette_sequence=cassette_sequence,
            cassette_sequence_status=cassette_status,
            unit_conversion=unit_conversion,
            unit_conversion_status=unit_status,
            input_count=max(current.input_count, candidate.input_count),
            evidence=dedupe_strings([*current.evidence, *candidate.evidence]),
        )
    return list(merged.values())


def merge_gate_candidates(candidates: list[PaperGateCandidate]) -> list[PaperGateCandidate]:
    merged: dict[str, PaperGateCandidate] = {}
    for candidate in candidates:
        key = candidate.name
        current = merged.get(key)
        if current is None:
            merged[key] = candidate
            continue
        promoter_sequence, promoter_status = _pick_by_status(
            current.output_promoter_sequence,
            current.output_promoter_sequence_status,
            candidate.output_promoter_sequence,
            candidate.output_promoter_sequence_status,
        )
        merged[key] = PaperGateCandidate(
            name=current.name,
            gate_type=_pick_text(candidate.gate_type, current.gate_type) or current.gate_type,
            regulator=_pick_text(current.regulator, candidate.regulator),
            output_promoter_name=_pick_text(current.output_promoter_name, candidate.output_promoter_name),
            output_promoter_sequence=promoter_sequence,
            output_promoter_sequence_status=promoter_status,
            response_function=_pick_text(candidate.response_function, current.response_function),
            parameters=merge_parameters([*current.parameters, *candidate.parameters]),
            evidence=dedupe_strings([*current.evidence, *candidate.evidence]),
        )
    return list(merged.values())


def merge_ucf_drafts(
    drafts: list[PaperUCFDraft],
    *,
    title: str | None = None,
    source_label: str | None = None,
) -> PaperUCFDraft:
    if not drafts:
        raise ValueError("At least one draft is required to merge UCF knowledge.")

    first = drafts[0]
    return PaperUCFDraft(
        paper_title=title or _pick_text(*(draft.paper_title for draft in drafts)) or "Merged UCF draft",
        paper_summary=" ".join(
            dedupe_strings([draft.paper_summary for draft in drafts if draft.paper_summary.strip()])
        ),
        source_path=source_label or " | ".join(
            dedupe_strings([draft.source_path for draft in drafts if draft.source_path.strip()])
        ),
        base_library_version=_pick_text(*(draft.base_library_version for draft in drafts)) or first.base_library_version,
        target_chassis=_pick_text(*(draft.target_chassis for draft in drafts)),
        source_organism=_pick_text(*(draft.source_organism for draft in drafts)),
        custom_input_sensors=merge_sensor_candidates(
            [sensor for draft in drafts for sensor in draft.custom_input_sensors]
        ),
        custom_output_devices=merge_output_candidates(
            [device for draft in drafts for device in draft.custom_output_devices]
        ),
        candidate_gates=merge_gate_candidates(
            [gate for draft in drafts for gate in draft.candidate_gates]
        ),
        missing_information=dedupe_strings(
            [item for draft in drafts for item in draft.missing_information]
        ),
        inference_notes=dedupe_strings(
            [item for draft in drafts for item in draft.inference_notes]
        ),
        warnings=dedupe_strings([item for draft in drafts for item in draft.warnings]),
    )


def build_input_sensor_draft(draft: PaperUCFDraft) -> list[dict]:
    return [
        {
            "name": sensor.name,
            "inducer": sensor.inducer,
            "promoter_name": sensor.promoter_name,
            "promoter_sequence": sensor.promoter_sequence,
            "promoter_sequence_status": sensor.promoter_sequence_status,
            "response_function": sensor.response_function,
            "parameters": [json.loads(parameter.model_dump_json()) for parameter in sensor.parameters],
            "evidence": sensor.evidence,
        }
        for sensor in draft.custom_input_sensors
    ]


def build_output_device_draft(draft: PaperUCFDraft) -> list[dict]:
    return [
        {
            "name": output.name,
            "reporter": output.reporter,
            "cassette_name": output.cassette_name,
            "cassette_sequence": output.cassette_sequence,
            "cassette_sequence_status": output.cassette_sequence_status,
            "unit_conversion": output.unit_conversion,
            "unit_conversion_status": output.unit_conversion_status,
            "input_count": output.input_count,
            "evidence": output.evidence,
        }
        for output in draft.custom_output_devices
    ]


def _input_count_for_gate(gate_type: str) -> int:
    if gate_type.strip().upper() in {"NOT", "BUFFER"}:
        return 1
    return 2


def _build_generic_response_function(name: str) -> dict:
    return {
        "collection": "functions",
        "name": name,
        "equation": "ymin + (ymax - ymin) / (1.0 + (x / K)^n)",
        "variables": [
            {
                "name": "x",
                "map": "#//model/functions/input_composition",
            }
        ],
        "parameters": [
            {"name": "ymax", "map": "#//model/parameters/ymax"},
            {"name": "ymin", "map": "#//model/parameters/ymin"},
            {"name": "K", "map": "#//model/parameters/K"},
            {"name": "n", "map": "#//model/parameters/n"},
        ],
    }


def _stable_color(name: str) -> str:
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()
    return digest[:6].upper()


def _build_linear_input_composition(
    name: str = "linear_input_composition",
    *,
    input_count: int = 2,
) -> dict:
    if input_count <= 1:
        equation = "x1"
        variables = [{"name": "x1", "map": "#//structure/inputs/in1"}]
    else:
        equation = "x1 + x2"
        variables = [
            {"name": "x1", "map": "#//structure/inputs/in1"},
            {"name": "x2", "map": "#//structure/inputs/in2"},
        ]
    return {
        "collection": "functions",
        "name": name,
        "equation": equation,
        "variables": variables,
        "parameters": [],
    }


def build_ucf_fragment(draft: PaperUCFDraft) -> list[dict]:
    items: list[dict] = []
    response_function_names: set[str] = set()
    max_input_count = 1

    for gate in draft.candidate_gates:
        response_function = _safe_name(gate.response_function or "Hill_response", "Hill_response")
        response_function_names.add(response_function)
        model_name = f"{gate.name}_model"
        structure_name = f"{gate.name}_structure"
        input_count = _input_count_for_gate(gate.gate_type)
        max_input_count = max(max_input_count, input_count)

        items.append(
            {
                "collection": "gates",
                "name": gate.name,
                "regulator": gate.regulator or gate.name,
                "group": gate.regulator or gate.name,
                "gate_type": gate.gate_type,
                "system": gate.regulator or gate.gate_type or gate.name,
                "color": _stable_color(gate.name),
                "model": model_name,
                "structure": structure_name,
            }
        )
        items.append(
            {
                "collection": "models",
                "name": model_name,
                "functions": {
                    "response_function": response_function,
                    "input_composition": "linear_input_composition",
                },
                "parameters": [
                    json.loads(parameter.model_dump_json(exclude_none=True))
                    for parameter in gate.parameters
                ],
            }
        )
        inputs = [
            {"name": f"in{index}", "part_type": "promoter"}
            for index in range(1, input_count + 1)
        ]
        outputs = [gate.output_promoter_name] if gate.output_promoter_name else []
        components = [f"#in{index}" for index in range(1, input_count + 1)]
        cassette_name = f"{gate.name}_cassette"
        components.append(cassette_name)
        items.append(
            {
                "collection": "structures",
                "name": structure_name,
                "inputs": inputs,
                "outputs": outputs,
                "devices": [
                    {
                        "name": gate.name,
                        "components": components,
                    },
                    {
                        "name": cassette_name,
                        "components": [gate.regulator or gate.name],
                    },
                ],
            }
        )
        if gate.output_promoter_name and gate.output_promoter_sequence:
            items.append(
                {
                    "collection": "parts",
                    "type": "promoter",
                    "name": gate.output_promoter_name,
                    "dnasequence": gate.output_promoter_sequence,
                }
            )

    if any(name == "Hill_response" for name in response_function_names):
        items.append(_build_generic_response_function("Hill_response"))
    for function_name in sorted(response_function_names):
        if function_name != "Hill_response":
            items.append(_build_generic_response_function(function_name))
    if draft.candidate_gates:
        items.append(_build_linear_input_composition(input_count=max_input_count))
    return items


def _named_item_key(item: dict) -> tuple[str, str] | None:
    collection = item.get("collection")
    name = item.get("name")
    if collection and name:
        return (collection, name)
    return None


def _merge_available_gates(base_item: dict, fragment: list[dict]) -> dict:
    merged = deepcopy(base_item)
    available = list(merged.get("available_gates", []))
    existing = {
        gate["type"]
        for gate in available
        if isinstance(gate, dict) and gate.get("type")
    }
    fragment_gate_types = sorted(
        {
            item.get("gate_type")
            for item in fragment
            if item.get("collection") == "gates" and item.get("gate_type")
        }
    )
    for gate_type in fragment_gate_types:
        if gate_type in existing:
            continue
        available.append({"type": gate_type, "max_instances": True})
    merged["available_gates"] = available
    return merged


def build_generated_ucf(
    base_ucf_items: list[dict],
    draft: PaperUCFDraft,
    *,
    version: str | None = None,
    description: str | None = None,
    source_label: str | None = None,
) -> list[dict]:
    fragment = build_ucf_fragment(draft)
    fragment_index = {
        key: item
        for item in fragment
        if (key := _named_item_key(item)) is not None
    }
    header_item = next(
        (item for item in base_ucf_items if item.get("collection") == "header"),
        None,
    )
    generated_description = description or f"{draft.paper_title} custom UCF draft"
    if source_label:
        generated_description = f"{generated_description} | source: {source_label}"
    if header_item is None:
        header_item = {
            "collection": "header",
            "description": generated_description,
            "version": version or draft.base_library_version,
            "date": datetime.now(timezone.utc).strftime("%a %b %d %H:%M:%S UTC %Y"),
            "author": ["OpenAI Codex"],
            "organism": draft.source_organism or draft.target_chassis or "custom",
            "genome": draft.target_chassis or "custom chassis",
            "media": draft.paper_summary or "Generated from paper draft",
            "temperature": "37",
            "growth": "Generated from source draft",
        }
    else:
        header_item = deepcopy(header_item)
        header_item["description"] = generated_description
        header_item["version"] = version or draft.base_library_version
        header_item["date"] = datetime.now(timezone.utc).strftime("%a %b %d %H:%M:%S UTC %Y")
        if draft.source_organism:
            header_item["organism"] = draft.source_organism

    merged_items: list[dict] = []
    emitted_custom_keys: set[tuple[str, str]] = set()
    for item in base_ucf_items:
        collection = item.get("collection")
        if collection == "header":
            merged_items.append(header_item)
            continue
        if collection == "logic_constraints":
            merged_items.append(_merge_available_gates(item, fragment))
            continue
        key = _named_item_key(item)
        if key is not None and key in fragment_index:
            merged_items.append(deepcopy(fragment_index[key]))
            emitted_custom_keys.add(key)
            continue
        merged_items.append(deepcopy(item))

    for item in fragment:
        key = _named_item_key(item)
        if key is not None and key in emitted_custom_keys:
            continue
        merged_items.append(deepcopy(item))

    return merged_items


def write_generated_ucf(
    base_ucf_path: Path,
    draft: PaperUCFDraft,
    output_path: Path,
    *,
    version: str | None = None,
    description: str | None = None,
    source_label: str | None = None,
) -> Path:
    text = base_ucf_path.read_text(encoding="utf-8")
    text = re.sub(r",\s*([}\]])", r"\1", text)
    base_ucf_items = json.loads(text)
    generated = build_generated_ucf(
        base_ucf_items,
        draft,
        version=version,
        description=description,
        source_label=source_label,
    )
    output_path.write_text(json.dumps(generated, indent=2) + "\n")
    return output_path


def write_ucf_draft_artifacts(run_dir: Path, draft: PaperUCFDraft) -> dict[str, Path]:
    files = {
        "input_sensor_draft_file": run_dir / "input_sensor_draft.json",
        "output_device_draft_file": run_dir / "output_device_draft.json",
        "ucf_fragment_file": run_dir / "ucf_fragment.json",
    }
    files["input_sensor_draft_file"].write_text(
        json.dumps(build_input_sensor_draft(draft), indent=2) + "\n"
    )
    files["output_device_draft_file"].write_text(
        json.dumps(build_output_device_draft(draft), indent=2) + "\n"
    )
    files["ucf_fragment_file"].write_text(
        json.dumps(build_ucf_fragment(draft), indent=2) + "\n"
    )
    return files