from __future__ import annotations

import re
from abc import ABC, abstractmethod

from openai import OpenAI

from .config import Settings
from .library import CelloLibraryIndex
from .models import CustomPartRequest, DesignSpec, InputSignalSpec, OutputSignalSpec
from .prompts import PLANNER_INSTRUCTIONS, build_planner_input


DEFAULT_VALIDATION_CHECKS = [
    "Validate generated input/output/UCF JSON files against the official Cello schemas.",
    "Confirm the chosen library has enough compatible sensors and reporter devices.",
    "Run Docker-based Cello compilation and inspect generated output artifacts.",
]


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    if not slug:
        slug = "bio_design"
    if slug[0].isdigit():
        slug = f"design_{slug}"
    return slug


def _clean_identifier(text: str | None, fallback: str) -> str:
    candidate = _slugify(text or fallback)
    return candidate or fallback


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        stripped = item.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        result.append(stripped)
    return result


def _make_unique_names(names: list[str], prefix: str) -> list[str]:
    used: dict[str, int] = {}
    unique: list[str] = []
    for index, raw_name in enumerate(names, start=1):
        base = _clean_identifier(raw_name, f"{prefix}{index}")
        count = used.get(base, 0)
        used[base] = count + 1
        unique.append(base if count == 0 else f"{base}_{count + 1}")
    return unique


def _build_verilog(
    module_name: str,
    input_names: list[str],
    operator: str,
    output_name: str = "out",
) -> str:
    inputs_decl = ",\n ".join(input_names + [output_name])
    assign_expr = {
        "AND": " & ".join(input_names),
        "OR": " | ".join(input_names),
        "XOR": " ^ ".join(input_names),
        "NOT": f"~{input_names[0]}",
        "NAND": f"~({' & '.join(input_names)})",
        "NOR": f"~({' | '.join(input_names)})",
    }[operator]
    input_lines = "\n".join(f"  input {name};" for name in input_names)
    return (
        f"module {module_name}\n"
        "(\n"
        f" {inputs_decl}\n"
        ");\n\n"
        f"{input_lines}\n"
        f"  output {output_name};\n\n"
        f"  assign {output_name} = {assign_expr};\n\n"
        f"endmodule // {module_name}\n"
    )


def _extract_declared_signals(verilog_code: str, keyword: str) -> list[str]:
    names: list[str] = []
    pattern = re.compile(rf"\b{keyword}\b\s+(?:wire\s+|reg\s+)?([^;]+);")
    for block in pattern.findall(verilog_code):
        for name in block.split(","):
            candidate = name.strip()
            if not candidate:
                continue
            names.append(_clean_identifier(candidate, f"{keyword}{len(names) + 1}"))
    return names


def _extract_module_name(verilog_code: str) -> str | None:
    match = re.search(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_]*)", verilog_code)
    return match.group(1) if match else None


def _infer_logic_operator_from_text(text: str) -> str | None:
    lowered = text.lower()
    checks = (
        ("xor", "XOR"),
        ("nand", "NAND"),
        ("nor", "NOR"),
        (" not ", "NOT"),
        ("invert", "NOT"),
        (" or ", "OR"),
        ("either", "OR"),
        (" and ", "AND"),
        ("both", "AND"),
    )
    for needle, operator in checks:
        if needle in lowered:
            return operator
    return None


def _infer_logic_operator(spec: DesignSpec, user_request: str) -> str:
    verilog = spec.verilog_code
    if "~(" in verilog and "&" in verilog:
        return "NAND"
    if "~(" in verilog and "|" in verilog:
        return "NOR"
    if "^" in verilog:
        return "XOR"
    if "&" in verilog:
        return "AND"
    if "|" in verilog:
        return "OR"
    if "~" in verilog:
        return "NOT"

    for text in (spec.logic_description, spec.summary, user_request):
        inferred = _infer_logic_operator_from_text(text)
        if inferred:
            return inferred
    return "AND"


def _infer_requested_input_count(user_request: str, spec: DesignSpec) -> int:
    lowered = user_request.lower()
    if re.search(r"\b(three|3)[ -]?input\b", lowered) or " three " in lowered:
        return max(3, len(spec.inputs), len(spec.selected_sensor_names))
    if re.search(r"\b(two|2)[ -]?input\b", lowered) or " both " in lowered:
        return max(2, len(spec.inputs), len(spec.selected_sensor_names))
    if " and " in lowered or "xor" in lowered or "either" in lowered:
        return max(2, len(spec.inputs), len(spec.selected_sensor_names))
    return max(1, len(spec.inputs), len(spec.selected_sensor_names))


def normalize_design_spec(
    spec: DesignSpec,
    library: CelloLibraryIndex,
    user_request: str,
) -> DesignSpec:
    requested_input_count = _infer_requested_input_count(user_request, spec)
    target_chassis = spec.target_chassis or "Eco"
    requested_sensors = _dedupe_preserve_order(
        [signal.preferred_sensor for signal in spec.inputs if signal.preferred_sensor]
        + list(spec.selected_sensor_names)
    )
    record = library.choose_record(
        target_chassis,
        required_sensor_count=requested_input_count,
        preferred_sensors=requested_sensors,
        preferred_output_device=spec.selected_output_device_name or spec.output.preferred_device,
    )

    manual_review_notes = list(spec.manual_review_notes)
    custom_part_requests = list(spec.custom_part_requests)
    constraints = _dedupe_preserve_order(list(spec.constraints))
    validation_checks = _dedupe_preserve_order(
        list(spec.validation_checks) + DEFAULT_VALIDATION_CHECKS
    )

    selected_sensors: list[str] = []
    for sensor_name in requested_sensors:
        if sensor_name in record.sensors and sensor_name not in selected_sensors:
            selected_sensors.append(sensor_name)
        else:
            manual_review_notes.append(
                f"Requested sensor '{sensor_name}' is not present in the official local library {record.version}."
            )
            custom_part_requests.append(
                CustomPartRequest(
                    name=sensor_name,
                    part_type="input_sensor",
                    reason="Requested or inferred by the planner but missing from the official local Cello library.",
                )
            )

    for sensor_name in record.sensors:
        if sensor_name not in selected_sensors:
            selected_sensors.append(sensor_name)
        if len(selected_sensors) >= requested_input_count:
            break

    if len(selected_sensors) < requested_input_count:
        manual_review_notes.append(
            f"The chosen library {record.version} only provides {len(selected_sensors)} usable sensor(s) for a request that appears to need {requested_input_count} input(s)."
        )

    preferred_output = spec.selected_output_device_name or spec.output.preferred_device
    if preferred_output and preferred_output not in record.output_devices:
        manual_review_notes.append(
            f"Requested output device '{preferred_output}' is not present in the official local library {record.version}. Falling back to {record.output_devices[0]}."
        )
        custom_part_requests.append(
            CustomPartRequest(
                name=preferred_output,
                part_type="output_device",
                reason="Requested or inferred by the planner but missing from the official local Cello library.",
            )
        )
    selected_output = (
        preferred_output
        if preferred_output in record.output_devices
        else record.output_devices[0]
    )

    operator = _infer_logic_operator(spec, user_request)
    parsed_input_names = _extract_declared_signals(spec.verilog_code, "input")
    parsed_output_names = _extract_declared_signals(spec.verilog_code, "output")
    parsed_module_name = _extract_module_name(spec.verilog_code)
    usable_verilog = (
        "module" in spec.verilog_code
        and "assign" in spec.verilog_code
        and "endmodule" in spec.verilog_code
        and len(parsed_input_names) == requested_input_count
        and len(parsed_output_names) >= 1
    )

    if usable_verilog:
        input_names = _make_unique_names(parsed_input_names, "in")
        output_name = _clean_identifier(parsed_output_names[0], "out")
        module_name = _clean_identifier(
            parsed_module_name or spec.verilog_module_name,
            f"{operator.lower()}_{record.chassis}_biosensor_gate",
        )
        verilog_code = spec.verilog_code.strip() + "\n"
    else:
        input_names = _make_unique_names(
            [signal.name for signal in spec.inputs[:requested_input_count]]
            or [f"in{index}" for index in range(1, requested_input_count + 1)],
            "in",
        )
        output_name = _clean_identifier(spec.output.name, "out")
        module_name = _clean_identifier(
            spec.verilog_module_name or f"{operator.lower()}_{record.chassis}_biosensor_gate",
            f"{operator.lower()}_{record.chassis}_biosensor_gate",
        )
        verilog_code = _build_verilog(module_name, input_names, operator, output_name)
        manual_review_notes.append(
            "Verilog was regenerated locally to keep the design spec consistent with the requested input count and naming."
        )

    normalized_inputs: list[InputSignalSpec] = []
    for index, input_name in enumerate(input_names):
        source = spec.inputs[index] if index < len(spec.inputs) else None
        preferred_sensor = selected_sensors[index] if index < len(selected_sensors) else None
        normalized_inputs.append(
            InputSignalSpec(
                name=input_name,
                description=(
                    source.description
                    if source and source.description
                    else f"Input signal {index + 1} extracted from the natural-language request."
                ),
                preferred_sensor=preferred_sensor,
            )
        )

    normalized_output = OutputSignalSpec(
        name=output_name,
        description=(
            spec.output.description
            if spec.output.description
            else "Reporter output for the designed circuit."
        ),
        preferred_device=selected_output,
    )

    return DesignSpec(
        design_name=spec.design_name.strip() or "Synthetic biology design draft",
        summary=spec.summary.strip() or user_request,
        target_chassis=record.chassis,
        inputs=normalized_inputs,
        output=normalized_output,
        logic_description=spec.logic_description.strip() or f"{operator} logic design.",
        verilog_module_name=module_name,
        verilog_code=verilog_code,
        selected_sensor_names=selected_sensors[:requested_input_count],
        selected_output_device_name=selected_output,
        constraints=constraints or [
            "Review gate count, chassis fit, and reporter compatibility before compilation."
        ],
        custom_part_requests=[
            CustomPartRequest.model_validate(item.model_dump())
            for item in _dedupe_custom_requests(custom_part_requests)
        ],
        validation_checks=validation_checks,
        manual_review_notes=_dedupe_preserve_order(manual_review_notes),
    )


def _dedupe_custom_requests(
    requests: list[CustomPartRequest],
) -> list[CustomPartRequest]:
    seen: set[tuple[str, str]] = set()
    unique: list[CustomPartRequest] = []
    for request in requests:
        key = (request.name, request.part_type)
        if key in seen:
            continue
        seen.add(key)
        unique.append(request)
    return unique


class Planner(ABC):
    @abstractmethod
    def plan(self, user_request: str, library: CelloLibraryIndex) -> DesignSpec:
        raise NotImplementedError


class OpenAIPlanner(Planner):
    def __init__(self, settings: Settings) -> None:
        self._client = OpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_model

    def plan(self, user_request: str, library: CelloLibraryIndex) -> DesignSpec:
        if not hasattr(self._client.responses, "parse"):
            raise RuntimeError(
                "The installed openai package does not expose responses.parse; upgrade the package."
            )

        response = self._client.responses.parse(
            model=self._model,
            instructions=PLANNER_INSTRUCTIONS,
            input=build_planner_input(user_request, library),
            text_format=DesignSpec,
            temperature=0.2,
            max_output_tokens=2400,
            store=False,
        )
        if response.output_parsed is None:
            raise RuntimeError("OpenAI did not return a parsed DesignSpec.")
        return normalize_design_spec(response.output_parsed, library, user_request)


class HeuristicPlanner(Planner):
    SENSOR_HINTS = (
        (("iptg", "lactose", "lac"), "LacI_sensor"),
        (("tet", "tetracycline", "atc"), "TetR_sensor"),
        (("arabinose", "ara"), "AraC_sensor"),
        (("ahl", "lux", "quorum"), "LuxR_sensor"),
    )

    def plan(self, user_request: str, library: CelloLibraryIndex) -> DesignSpec:
        lowered = user_request.lower()
        target_chassis = "Eco"
        if "bacillus" in lowered or "bth" in lowered:
            target_chassis = "Bth"
        elif "saccharomyces" in lowered or "yeast" in lowered or "sc " in lowered:
            target_chassis = "SC"

        input_count = self._detect_input_count(lowered)
        record = library.choose_record(target_chassis, required_sensor_count=input_count)
        operator = self._detect_logic_operator(lowered)
        selected_sensors = self._choose_sensors(lowered, record.sensors, input_count)
        output_device = record.output_devices[0] if record.output_devices else None

        module_stem = _slugify(f"{operator.lower()}_{record.chassis}_biosensor")
        module_name = f"{module_stem}_gate"
        input_names = [f"in{i}" for i in range(1, input_count + 1)]
        verilog_code = _build_verilog(module_name, input_names, operator)

        return DesignSpec(
            design_name=f"{operator} biosensor draft",
            summary=user_request,
            target_chassis=record.chassis,
            inputs=[
                InputSignalSpec(
                    name=input_name,
                    description=f"Input signal placeholder mapped to {sensor_name}",
                    preferred_sensor=sensor_name,
                )
                for input_name, sensor_name in zip(input_names, selected_sensors, strict=False)
            ],
            output=OutputSignalSpec(
                name="out",
                description="Reporter output for the designed circuit",
                preferred_device=output_device,
            ),
            logic_description=f"Heuristic {operator} logic inferred from the natural-language request.",
            verilog_module_name=module_name,
            verilog_code=verilog_code,
            selected_sensor_names=selected_sensors,
            selected_output_device_name=output_device,
            constraints=self._detect_constraints(lowered),
            validation_checks=[
                *DEFAULT_VALIDATION_CHECKS,
            ],
            manual_review_notes=[
                "Heuristic planner was used. Add OPENAI_API_KEY to use the OpenAI-backed structured planner.",
                "If the requested biological input is missing from the official local library, add a custom UCF curation step.",
            ],
        )

    def _detect_input_count(self, lowered: str) -> int:
        if re.search(r"\b(three|3)[ -]?input\b", lowered) or " three " in lowered:
            return 3
        if re.search(r"\b(two|2)[ -]?input\b", lowered) or " both " in lowered:
            return 2
        if " and " in lowered or "xor" in lowered or "either" in lowered:
            return 2
        return 1

    def _detect_logic_operator(self, lowered: str) -> str:
        if "xor" in lowered:
            return "XOR"
        if "nand" in lowered:
            return "NAND"
        if "nor" in lowered:
            return "NOR"
        if " or " in lowered or "either" in lowered:
            return "OR"
        if " not " in lowered or "invert" in lowered:
            return "NOT"
        return "AND"

    def _choose_sensors(
        self,
        lowered: str,
        available_sensors: tuple[str, ...],
        count: int,
    ) -> list[str]:
        picked: list[str] = []
        for keywords, sensor_name in self.SENSOR_HINTS:
            if any(keyword in lowered for keyword in keywords) and sensor_name in available_sensors:
                picked.append(sensor_name)
        for sensor_name in available_sensors:
            if sensor_name not in picked:
                picked.append(sensor_name)
            if len(picked) >= count:
                break
        return picked[:count]

    def _detect_constraints(self, lowered: str) -> list[str]:
        constraints = []
        if "tox" in lowered or "burden" in lowered:
            constraints.append("Minimize host burden and review toxicity-related design choices.")
        if "leak" in lowered or "background" in lowered:
            constraints.append("Review leakiness and off-state repression before simulation.")
        if "fast" in lowered:
            constraints.append("Prefer a compact logic design with minimal gate depth.")
        if not constraints:
            constraints.append("Review gate count, chassis fit, and reporter compatibility before compilation.")
        return constraints


def build_planner(settings: Settings, force_heuristic: bool = False) -> Planner:
    if settings.openai_api_key and not force_heuristic:
        return OpenAIPlanner(settings)
    return HeuristicPlanner()
