from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI
from openai import RateLimitError as OpenAIRateLimitError
from pypdf import PdfReader

from .config import Settings
from .custom_library import CustomLibraryAuthor
from .library import CelloLibraryIndex
from .models import (
    CustomLibraryManifest,
    CustomLibrarySpec,
    CustomOutputDeviceDefinition,
    CustomSensorDefinition,
    PaperOutputDeviceCandidate,
    PaperSensorCandidate,
    PaperUCFDraft,
    UCFParameter,
)
from .prompts import PAPER_TO_UCF_INSTRUCTIONS, build_paper_to_ucf_input
from .ucf_drafts import dedupe_strings, write_generated_ucf, write_ucf_draft_artifacts


DEFAULT_SENSOR_YMAX = 5.0
DEFAULT_SENSOR_YMIN = 0.05
DEFAULT_OUTPUT_UNIT_CONVERSION = 1.0


def _slugify(text: str) -> str:
    chars = [character.lower() if character.isalnum() else "_" for character in text]
    slug = "".join(chars).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "paper_ucf_draft"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _normalize_sequence(sequence: str | None) -> str | None:
    if not sequence:
        return None
    cleaned = "".join(sequence.split()).upper()
    if not cleaned:
        return None
    invalid = {character for character in cleaned if character not in {"A", "T", "G", "C"}}
    if invalid:
        return None
    return cleaned


def _numeric_parameter(
    parameters: list[UCFParameter],
    *,
    name: str,
    default: float,
) -> float:
    for parameter in parameters:
        if parameter.name.lower() != name.lower():
            continue
        value = parameter.value
        if value is None:
            break
        try:
            return float(value)
        except (TypeError, ValueError):
            break
    return default


def load_source_text(source_path: Path, *, max_chars: int = 60000) -> str:
    suffix = source_path.suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(str(source_path))
        text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
    else:
        text = source_path.read_text()

    normalized = text.strip()
    if not normalized:
        raise ValueError(f"No readable text could be extracted from {source_path}")
    if len(normalized) > max_chars:
        return normalized[:max_chars]
    return normalized


@dataclass(frozen=True)
class PaperToUCFResult:
    draft: PaperUCFDraft
    run_directory: Path
    draft_file: Path
    summary_file: Path
    generated_ucf_file: Path
    input_sensor_draft_file: Path
    output_device_draft_file: Path
    ucf_fragment_file: Path
    custom_library_spec_file: Path | None
    custom_library_manifest: CustomLibraryManifest | None
    warnings: list[str]


class PaperToUCFAgent:
    def __init__(self, settings: Settings, library: CelloLibraryIndex) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        self._client = OpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_model
        self._library = library

    def extract(
        self,
        source_path: Path,
        *,
        base_version: str = "Eco1C1G1T1",
        max_chars: int = 60000,
        request_context: str | None = None,
    ) -> PaperUCFDraft:
        source_text = load_source_text(source_path, max_chars=max_chars)
        return self.extract_text(
            source_name=str(source_path),
            source_text=source_text,
            base_version=base_version,
            request_context=request_context,
        )

    def extract_text(
        self,
        *,
        source_name: str,
        source_text: str,
        base_version: str = "Eco1C1G1T1",
        request_context: str | None = None,
    ) -> PaperUCFDraft:
        if not hasattr(self._client.responses, "parse"):
            raise RuntimeError(
                "The installed openai package does not expose responses.parse; upgrade the package."
            )

        record = self._library.get_record(base_version)
        prompt = build_paper_to_ucf_input(
            source_name=source_name,
            source_text=source_text,
            base_library_summary=record.summary_line(),
            base_library_version=record.version,
            request_context=request_context,
        )

        try:
            response = self._client.responses.parse(
                model=self._model,
                instructions=PAPER_TO_UCF_INSTRUCTIONS,
                input=prompt,
                text_format=PaperUCFDraft,
            )
        except OpenAIRateLimitError as exc:
            raise RuntimeError(
                "OpenAI API request failed because the current project has no usable quota. "
                "Add billing or credits in platform.openai.com, then rerun the extraction."
            ) from exc

        if response.output_parsed is None:
            raise RuntimeError("OpenAI did not return a parsed PaperUCFDraft.")
        return response.output_parsed


class PaperToUCFPipeline:
    def __init__(self, settings: Settings, library: CelloLibraryIndex) -> None:
        self._settings = settings
        self._library = library
        self._extractor = PaperToUCFAgent(settings, library)
        self._author = CustomLibraryAuthor(library, settings.cello_root)

    def run(
        self,
        source_path: Path,
        *,
        output_dir: Path | None = None,
        base_version: str = "Eco1C1G1T1",
        max_chars: int = 60000,
        author_custom_library: bool = True,
        request_context: str | None = None,
    ) -> PaperToUCFResult:
        draft = self._extractor.extract(
            source_path,
            base_version=base_version,
            max_chars=max_chars,
            request_context=request_context,
        )
        return self.materialize_draft(
            draft,
            source_name=str(source_path),
            output_dir=output_dir,
            run_name=_slugify(source_path.stem),
            author_custom_library=author_custom_library,
        )

    def run_text(
        self,
        *,
        source_name: str,
        source_text: str,
        output_dir: Path | None = None,
        base_version: str = "Eco1C1G1T1",
        author_custom_library: bool = True,
        request_context: str | None = None,
        run_name: str | None = None,
    ) -> PaperToUCFResult:
        draft = self._extractor.extract_text(
            source_name=source_name,
            source_text=source_text,
            base_version=base_version,
            request_context=request_context,
        )
        return self.materialize_draft(
            draft,
            source_name=source_name,
            output_dir=output_dir,
            run_name=run_name or _slugify(source_name),
            author_custom_library=author_custom_library,
        )

    def materialize_draft(
        self,
        draft: PaperUCFDraft,
        *,
        source_name: str,
        output_dir: Path | None = None,
        run_name: str = "ucf_draft",
        author_custom_library: bool = True,
    ) -> PaperToUCFResult:
        output_root = output_dir or (self._settings.output_root / "paper_ucf")
        run_dir = output_root / run_name
        run_dir.mkdir(parents=True, exist_ok=True)

        draft_file = run_dir / "paper_ucf_draft.json"
        summary_file = run_dir / "summary.md"
        generated_ucf_file = run_dir / "generated.UCF.json"
        custom_library_spec_file: Path | None = None
        custom_library_manifest: CustomLibraryManifest | None = None

        warnings = list(draft.warnings)
        _write_json(draft_file, json.loads(draft.model_dump_json(indent=2)))
        draft_artifacts = write_ucf_draft_artifacts(run_dir, draft)
        write_generated_ucf(
            self._library.get_record(draft.base_library_version).ucf_file,
            draft,
            generated_ucf_file,
            version=f"{draft.base_library_version}_generated",
            description=f"{draft.paper_title} generated UCF draft",
            source_label=draft.source_path,
        )

        custom_spec, conversion_warnings = self._draft_to_custom_library_spec(draft)
        warnings.extend(conversion_warnings)
        if author_custom_library and custom_spec is not None:
            custom_library_spec_file = run_dir / "custom_library_spec.json"
            _write_json(custom_library_spec_file, json.loads(custom_spec.model_dump_json(indent=2)))
            custom_library_manifest = self._author.author(
                custom_spec,
                run_dir / "compiled_library",
                ucf_file=generated_ucf_file,
            )

        warnings = dedupe_strings(warnings)
        summary_file.write_text(
            self._build_summary(
                source_name=source_name,
                draft=draft,
                generated_ucf_file=generated_ucf_file,
                warnings=warnings,
                custom_library_manifest=custom_library_manifest,
            )
        )

        return PaperToUCFResult(
            draft=draft,
            run_directory=run_dir,
            draft_file=draft_file,
            summary_file=summary_file,
            generated_ucf_file=generated_ucf_file,
            input_sensor_draft_file=draft_artifacts["input_sensor_draft_file"],
            output_device_draft_file=draft_artifacts["output_device_draft_file"],
            ucf_fragment_file=draft_artifacts["ucf_fragment_file"],
            custom_library_spec_file=custom_library_spec_file,
            custom_library_manifest=custom_library_manifest,
            warnings=warnings,
        )

    def _draft_to_custom_library_spec(
        self,
        draft: PaperUCFDraft,
    ) -> tuple[CustomLibrarySpec | None, list[str]]:
        warnings: list[str] = []
        sensors: list[CustomSensorDefinition] = []
        outputs: list[CustomOutputDeviceDefinition] = []

        for sensor in draft.custom_input_sensors:
            converted, warning = self._convert_sensor(sensor)
            if converted is not None:
                sensors.append(converted)
            if warning:
                warnings.append(warning)

        for output_device in draft.custom_output_devices:
            converted, warning = self._convert_output(output_device)
            if converted is not None:
                outputs.append(converted)
            if warning:
                warnings.append(warning)

        if not sensors and not outputs:
            warnings.append(
                "No custom library bundle was generated because the extracted draft did not include enough sequence-backed sensor or output entries."
            )
            return None, warnings

        return (
            CustomLibrarySpec(
                library_name=f"{draft.paper_title} draft library",
                base_version=draft.base_library_version,
                custom_input_sensors=sensors,
                custom_output_devices=outputs,
                notes=list(draft.inference_notes) + list(draft.missing_information),
            ),
            warnings,
        )

    def _convert_sensor(
        self,
        sensor: PaperSensorCandidate,
    ) -> tuple[CustomSensorDefinition | None, str | None]:
        sequence = _normalize_sequence(sensor.promoter_sequence)
        if not sequence:
            return (
                None,
                f"Skipped sensor '{sensor.name}' during custom library authoring because no usable promoter sequence was available.",
            )

        ymax = _numeric_parameter(sensor.parameters, name="ymax", default=DEFAULT_SENSOR_YMAX)
        ymin = _numeric_parameter(sensor.parameters, name="ymin", default=DEFAULT_SENSOR_YMIN)
        alpha = None
        beta = None
        for parameter in sensor.parameters:
            if parameter.name.lower() == "alpha":
                try:
                    alpha = float(parameter.value) if parameter.value is not None else None
                except (TypeError, ValueError):
                    alpha = None
            if parameter.name.lower() == "beta":
                try:
                    beta = float(parameter.value) if parameter.value is not None else None
                except (TypeError, ValueError):
                    beta = None

        return (
            CustomSensorDefinition(
                name=sensor.name,
                promoter_name=sensor.promoter_name,
                promoter_sequence=sequence,
                ymax=ymax,
                ymin=ymin,
                alpha=alpha,
                beta=beta,
            ),
            None,
        )

    def _convert_output(
        self,
        output_device: PaperOutputDeviceCandidate,
    ) -> tuple[CustomOutputDeviceDefinition | None, str | None]:
        sequence = _normalize_sequence(output_device.cassette_sequence)
        if not sequence:
            return (
                None,
                f"Skipped output device '{output_device.name}' during custom library authoring because no usable cassette sequence was available.",
            )

        unit_conversion = (
            float(output_device.unit_conversion)
            if output_device.unit_conversion is not None
            else DEFAULT_OUTPUT_UNIT_CONVERSION
        )
        return (
            CustomOutputDeviceDefinition(
                name=output_device.name,
                cassette_name=output_device.cassette_name,
                cassette_sequence=sequence,
                unit_conversion=unit_conversion,
                input_count=output_device.input_count,
            ),
            None,
        )

    def _build_summary(
        self,
        *,
        source_name: str,
        draft: PaperUCFDraft,
        generated_ucf_file: Path,
        warnings: list[str],
        custom_library_manifest: CustomLibraryManifest | None,
    ) -> str:
        sensor_lines = (
            "\n".join(
                f"- {sensor.name}: promoter={sensor.promoter_name}, sequence_status={sensor.promoter_sequence_status}"
                for sensor in draft.custom_input_sensors
            )
            or "- None"
        )
        output_lines = (
            "\n".join(
                f"- {output.name}: cassette={output.cassette_name}, sequence_status={output.cassette_sequence_status}"
                for output in draft.custom_output_devices
            )
            or "- None"
        )
        gate_lines = (
            "\n".join(
                f"- {gate.name}: type={gate.gate_type}, regulator={gate.regulator or 'unknown'}"
                for gate in draft.candidate_gates
            )
            or "- None"
        )
        warning_lines = "\n".join(f"- {warning}" for warning in warnings) or "- None"
        missing_lines = "\n".join(f"- {item}" for item in draft.missing_information) or "- None"
        inference_lines = "\n".join(f"- {item}" for item in draft.inference_notes) or "- None"
        compiled_line = (
            f"- Generated custom library bundle: {custom_library_manifest.run_directory}"
            if custom_library_manifest is not None
            else "- No schema-valid custom library bundle was generated from this draft."
        )
        return (
            f"# {draft.paper_title}\n\n"
            "## Source\n\n"
            f"- File: {source_name}\n"
            f"- Base library: {draft.base_library_version}\n"
            f"- Target chassis: {draft.target_chassis or 'not set'}\n"
            f"- Source organism: {draft.source_organism or 'not set'}\n\n"
            "## Generated UCF\n\n"
            f"- File: {generated_ucf_file}\n"
            f"- Custom bundle UCF: {custom_library_manifest.ucf_file if custom_library_manifest is not None else 'not generated'}\n\n"
            "## Summary\n\n"
            f"{draft.paper_summary}\n\n"
            "## Extracted Sensors\n\n"
            f"{sensor_lines}\n\n"
            "## Extracted Outputs\n\n"
            f"{output_lines}\n\n"
            "## Candidate Gates\n\n"
            f"{gate_lines}\n\n"
            "## Missing Information\n\n"
            f"{missing_lines}\n\n"
            "## Inference Notes\n\n"
            f"{inference_lines}\n\n"
            "## Automation Result\n\n"
            f"{compiled_line}\n\n"
            "## Warnings\n\n"
            f"{warning_lines}\n"
        )
