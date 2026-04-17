from __future__ import annotations

import json
from pathlib import Path

from .library import CelloLibraryIndex
from .models import DesignBrief, DesignSpec, InputSignalSpec, OutputSignalSpec
from .planner import DEFAULT_VALIDATION_CHECKS, _build_verilog, _clean_identifier, normalize_design_spec


SENSOR_HINTS = (
    (("iptg", "lactose", "lac"), "LacI_sensor"),
    (("tet", "tetracycline", "atc"), "TetR_sensor"),
    (("arabinose", "ara"), "AraC_sensor"),
    (("ahl", "lux", "quorum"), "LuxR_sensor"),
)

OUTPUT_HINTS = (
    (("yfp", "yellow fluorescent"), "YFP_reporter"),
    (("gfp", "green fluorescent"), "GFP_reporter"),
    (("bfp", "blue fluorescent"), "BFP_reporter"),
    (("rfp", "red fluorescent"), "RFP_reporter"),
)


def load_design_brief(path: Path) -> DesignBrief:
    return DesignBrief.model_validate_json(path.read_text())


def _infer_sensor_name(
    signal_name: str | None,
    preferred_sensor: str | None,
) -> str | None:
    if preferred_sensor:
        return preferred_sensor
    lowered = (signal_name or "").lower()
    for keywords, sensor_name in SENSOR_HINTS:
        if any(keyword in lowered for keyword in keywords):
            return sensor_name
    return None


def _infer_output_device(
    signal_name: str | None,
    preferred_device: str | None,
) -> str | None:
    if preferred_device:
        return preferred_device
    lowered = (signal_name or "").lower()
    for keywords, device_name in OUTPUT_HINTS:
        if any(keyword in lowered for keyword in keywords):
            return device_name
    return None


def compile_design_brief(
    brief: DesignBrief,
    library: CelloLibraryIndex,
) -> DesignSpec:
    operator = brief.logic_operator.strip().upper()
    input_names = [
        _clean_identifier(signal.logical_name, f"in{index}")
        for index, signal in enumerate(brief.input_signals, start=1)
    ]
    output_name = _clean_identifier(brief.output_signal.logical_name, "out")
    module_name = _clean_identifier(
        f"{brief.design_name}_{operator.lower()}_gate",
        "bio_logic_gate",
    )
    verilog_code = _build_verilog(module_name, input_names, operator, output_name)

    preliminary_spec = DesignSpec(
        design_name=brief.design_name,
        summary=brief.summary,
        target_chassis=brief.target_chassis,
        inputs=[
            InputSignalSpec(
                name=input_name,
                description=signal.description,
                preferred_sensor=_infer_sensor_name(signal.signal_name, signal.preferred_sensor),
            )
            for input_name, signal in zip(input_names, brief.input_signals, strict=False)
        ],
        output=OutputSignalSpec(
            name=output_name,
            description=brief.output_signal.description,
            preferred_device=_infer_output_device(
                brief.output_signal.signal_name,
                brief.output_signal.preferred_device,
            ),
        ),
        logic_description=f"{operator} logic circuit defined from a structured design brief.",
        verilog_module_name=module_name,
        verilog_code=verilog_code,
        selected_sensor_names=[
            sensor_name
            for signal in brief.input_signals
            if (sensor_name := _infer_sensor_name(signal.signal_name, signal.preferred_sensor))
        ],
        selected_output_device_name=_infer_output_device(
            brief.output_signal.signal_name,
            brief.output_signal.preferred_device,
        ),
        constraints=list(brief.constraints)
        or ["Review gate count, chassis fit, and reporter compatibility before compilation."],
        validation_checks=list(DEFAULT_VALIDATION_CHECKS),
        manual_review_notes=list(brief.notes),
    )

    request_text = json.dumps(brief.model_dump(), ensure_ascii=False)
    return normalize_design_spec(preliminary_spec, library, request_text)
