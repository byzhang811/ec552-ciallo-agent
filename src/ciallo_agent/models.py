from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InputSignalSpec(StrictModel):
    name: str = Field(description="Short identifier for the logical input signal, such as in1 or arabinose.")
    description: str = Field(description="Human-readable explanation of what this input represents.")
    preferred_sensor: str | None = Field(
        default=None,
        description="Preferred official Cello input sensor name when one is available locally.",
    )


class OutputSignalSpec(StrictModel):
    name: str = Field(description="Short identifier for the logical output signal, usually out or y.")
    description: str = Field(description="Human-readable explanation of what the output represents.")
    preferred_device: str | None = Field(
        default=None,
        description="Preferred official Cello output device name when one is available locally.",
    )


class CustomPartRequest(StrictModel):
    name: str = Field(description="Name of the missing or custom biological part that still needs curation.")
    part_type: str = Field(description="Biological category such as input_sensor, output_device, promoter, gate, or model.")
    reason: str = Field(description="Why this custom part is needed.")
    sequence: str | None = Field(
        default=None,
        description="Optional DNA sequence if the user already supplied it.",
    )
    source_hint: str | None = Field(
        default=None,
        description="Optional external source hint such as SynBioHub, SBOL, or a paper identifier.",
    )


class DesignBriefInput(StrictModel):
    logical_name: str = Field(description="Stable logical signal name such as arabinose or in1.")
    description: str = Field(description="Short human-readable description of this logical input.")
    signal_name: str | None = Field(
        default=None,
        description="Optional user-facing name for the inducer or signal, such as IPTG or arabinose.",
    )
    preferred_sensor: str | None = Field(
        default=None,
        description="Preferred local Cello sensor name when the user already knows it.",
    )


class DesignBriefOutput(StrictModel):
    logical_name: str = Field(description="Stable logical output name such as y or reporter.")
    description: str = Field(description="Short human-readable description of the output.")
    signal_name: str | None = Field(
        default=None,
        description="Optional user-facing output label such as YFP or GFP reporter.",
    )
    preferred_device: str | None = Field(
        default=None,
        description="Preferred local Cello output device name when the user already knows it.",
    )


class DesignBrief(StrictModel):
    design_name: str = Field(description="Project or circuit name.")
    summary: str = Field(description="Short summary of the intended circuit behavior.")
    target_chassis: str | None = Field(
        default="Eco",
        description="Preferred chassis label such as Eco, SC, or Bth.",
    )
    logic_operator: str = Field(
        description="Boolean operator for the top-level logic such as AND, OR, XOR, NAND, NOR, or NOT.",
    )
    input_signals: list[DesignBriefInput] = Field(
        description="Ordered logical inputs for the circuit.",
    )
    output_signal: DesignBriefOutput = Field(description="Logical output signal for the circuit.")
    constraints: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class DesignSpec(StrictModel):
    design_name: str = Field(description="Short project name for the design request.")
    summary: str = Field(description="One- or two-sentence summary of the requested design.")
    target_chassis: str | None = Field(
        default="Eco",
        description="Preferred short chassis label such as Eco, SC, or Bth.",
    )
    inputs: list[InputSignalSpec] = Field(description="Logical inputs required by the design.")
    output: OutputSignalSpec = Field(description="Logical output signal for the design.")
    logic_description: str = Field(description="Plain-language explanation of the intended combinational logic.")
    verilog_module_name: str = Field(description="Top-level Verilog module name.")
    verilog_code: str = Field(description="Synthesizable combinational Verilog for the requested logic.")
    selected_sensor_names: list[str] = Field(
        default_factory=list,
        description="Preferred official Cello input sensors chosen from the local library whenever possible.",
    )
    selected_output_device_name: str | None = Field(
        default=None,
        description="Preferred official Cello output device chosen from the local library whenever possible.",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Practical design constraints, risk notes, or optimization goals.",
    )
    custom_part_requests: list[CustomPartRequest] = Field(
        default_factory=list,
        description="Missing parts or models that require later manual library curation.",
    )
    validation_checks: list[str] = Field(
        default_factory=list,
        description="Concrete pre-Cello checks to perform before or after bundle generation.",
    )
    manual_review_notes: list[str] = Field(
        default_factory=list,
        description="Anything that still needs user review, especially unsupported biology or ambiguous requirements.",
    )


class ArtifactManifest(StrictModel):
    run_name: str
    run_directory: str
    source_library_version: str
    source_library_chassis: str
    verilog_file: str
    input_file: str
    output_file: str
    ucf_file: str
    options_file: str
    spec_file: str
    summary_file: str
    cello_output_dir: str
    selected_sensors: list[str] = Field(default_factory=list)
    selected_output_device: str | None = None
    warnings: list[str] = Field(default_factory=list)


class CustomSensorDefinition(StrictModel):
    name: str = Field(description="Name of the custom input sensor.")
    promoter_name: str = Field(description="Promoter part name emitted by this sensor.")
    promoter_sequence: str = Field(description="DNA sequence for the promoter part.")
    ymax: float = Field(description="Maximum transcription strength for the sensor model.")
    ymin: float = Field(description="Minimum transcription strength for the sensor model.")
    alpha: float | None = Field(
        default=None,
        description="Optional tandem parameter alpha.",
    )
    beta: float | None = Field(
        default=None,
        description="Optional tandem parameter beta.",
    )


class CustomOutputDeviceDefinition(StrictModel):
    name: str = Field(description="Name of the custom output reporter device.")
    cassette_name: str = Field(description="Cassette part name used by the output device.")
    cassette_sequence: str = Field(description="DNA sequence for the cassette part.")
    unit_conversion: float = Field(
        default=1.0,
        description="Unit conversion factor for the reporter response model.",
    )
    input_count: int = Field(
        default=2,
        ge=1,
        description="How many promoter inputs this reporter structure expects.",
    )


class CustomLibrarySpec(StrictModel):
    library_name: str = Field(description="Human-readable name for the generated custom library bundle.")
    base_version: str = Field(
        default="Eco1C1G1T1",
        description="Official local Cello library version to extend.",
    )
    custom_input_sensors: list[CustomSensorDefinition] = Field(default_factory=list)
    custom_output_devices: list[CustomOutputDeviceDefinition] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class CustomLibraryManifest(StrictModel):
    library_name: str
    run_directory: str
    base_library_version: str
    base_library_chassis: str
    input_file: str
    output_file: str
    ucf_file: str
    summary_file: str
    spec_file: str
    warnings: list[str] = Field(default_factory=list)


FieldOrigin = Literal["extracted", "inferred", "defaulted", "missing"]


class UCFParameter(StrictModel):
    name: str = Field(description="Parameter name, such as ymax, ymin, K, or n.")
    value: float | int | str | None = Field(
        default=None,
        description="Extracted or inferred parameter value.",
    )
    status: FieldOrigin = Field(
        description="Whether the value was extracted from the paper, inferred, defaulted, or left missing.",
    )
    rationale: str = Field(
        description="Short explanation of where the value came from or why it is missing.",
    )


class PaperSensorCandidate(StrictModel):
    name: str = Field(description="Candidate name for the custom input sensor.")
    inducer: str | None = Field(
        default=None,
        description="Input signal or inducer for this sensor, if known.",
    )
    promoter_name: str = Field(description="Promoter emitted by this sensor.")
    promoter_sequence: str | None = Field(
        default=None,
        description="DNA sequence for the promoter when available.",
    )
    promoter_sequence_status: FieldOrigin = Field(
        default="missing",
        description="Whether the promoter sequence was extracted, inferred, defaulted, or missing.",
    )
    response_function: str = Field(
        default="sensor_response",
        description="Cello-style response function family to use for this sensor model.",
    )
    parameters: list[UCFParameter] = Field(
        default_factory=list,
        description="Candidate response-function parameters for this sensor.",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Bullet-style evidence notes copied or paraphrased from the source paper.",
    )


class PaperOutputDeviceCandidate(StrictModel):
    name: str = Field(description="Candidate name for the custom output device.")
    reporter: str | None = Field(
        default=None,
        description="Reporter protein or output mechanism, if known.",
    )
    cassette_name: str = Field(description="Cassette or device part name used by this output.")
    cassette_sequence: str | None = Field(
        default=None,
        description="DNA sequence for the cassette when available.",
    )
    cassette_sequence_status: FieldOrigin = Field(
        default="missing",
        description="Whether the cassette sequence was extracted, inferred, defaulted, or missing.",
    )
    unit_conversion: float | None = Field(
        default=None,
        description="Reporter conversion parameter if available.",
    )
    unit_conversion_status: FieldOrigin = Field(
        default="missing",
        description="Whether unit_conversion was extracted, inferred, defaulted, or missing.",
    )
    input_count: int = Field(
        default=2,
        ge=1,
        description="How many promoter inputs this reporter structure expects in Cello.",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Bullet-style evidence notes copied or paraphrased from the source paper.",
    )


class PaperGateCandidate(StrictModel):
    name: str = Field(description="Candidate name for the biological gate.")
    gate_type: str = Field(
        description="High-level gate family such as NOT, NOR, NAND, buffer, activator, or repressor cascade.",
    )
    regulator: str | None = Field(
        default=None,
        description="Primary regulatory protein or complex, if mentioned.",
    )
    output_promoter_name: str | None = Field(
        default=None,
        description="Promoter or output signal emitted by this gate.",
    )
    output_promoter_sequence: str | None = Field(
        default=None,
        description="DNA sequence for the gate output promoter when available.",
    )
    output_promoter_sequence_status: FieldOrigin = Field(
        default="missing",
        description="Whether the output promoter sequence was extracted, inferred, defaulted, or missing.",
    )
    response_function: str | None = Field(
        default=None,
        description="Candidate response function family for the gate model.",
    )
    parameters: list[UCFParameter] = Field(
        default_factory=list,
        description="Candidate gate-model parameters extracted or inferred from the paper.",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Bullet-style evidence notes copied or paraphrased from the source paper.",
    )


class PaperUCFDraft(StrictModel):
    paper_title: str = Field(description="Title or best-effort title of the source paper.")
    paper_summary: str = Field(description="Short summary of the biological system described in the source.")
    source_path: str = Field(description="Local source file path used for extraction.")
    base_library_version: str = Field(
        default="Eco1C1G1T1",
        description="Official local Cello library version that this draft is intended to extend.",
    )
    target_chassis: str | None = Field(
        default=None,
        description="Preferred target chassis label such as Eco, SC, or Bth.",
    )
    source_organism: str | None = Field(
        default=None,
        description="Organism actually described in the source paper, if known.",
    )
    custom_input_sensors: list[PaperSensorCandidate] = Field(default_factory=list)
    custom_output_devices: list[PaperOutputDeviceCandidate] = Field(default_factory=list)
    candidate_gates: list[PaperGateCandidate] = Field(default_factory=list)
    missing_information: list[str] = Field(
        default_factory=list,
        description="Critical fields the paper did not provide clearly enough for a faithful UCF build.",
    )
    inference_notes: list[str] = Field(
        default_factory=list,
        description="Places where the model inferred or normalized information beyond verbatim extraction.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="High-level caveats about reliability, missing data, or likely follow-up work.",
    )
