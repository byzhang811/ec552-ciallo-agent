from pathlib import Path

from ciallo_agent.config import Settings
from ciallo_agent.library import LibraryRecord
from ciallo_agent.models import DesignSpec, InputSignalSpec, OutputSignalSpec
from ciallo_agent.pipeline import CialloPipeline


REPO_ROOT = Path(__file__).resolve().parents[1]


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        repo_root=REPO_ROOT,
        cello_root=REPO_ROOT / "external" / "Cello-v2",
        output_root=tmp_path,
        openai_api_key=None,
        openai_model="gpt-4o-mini",
        cello_docker_image="cidarlab/cello-dnacompiler:latest",
        cello_python_env="python",
    )


def test_pipeline_generates_schema_valid_bundle(tmp_path: Path) -> None:
    pipeline = CialloPipeline(_settings(tmp_path))
    result = pipeline.run(
        "Design a 2-input AND biosensor that turns on a fluorescent reporter when arabinose and IPTG are both present.",
        force_heuristic=True,
    )

    assert result.manifest.selected_sensors
    assert Path(result.manifest.verilog_file).exists()
    assert Path(result.manifest.input_file).exists()
    assert Path(result.manifest.output_file).exists()
    assert Path(result.manifest.ucf_file).exists()
    assert result.validation_issues == []


def test_pipeline_can_use_augmented_library_override(tmp_path: Path) -> None:
    pipeline = CialloPipeline(_settings(tmp_path))
    base_record = pipeline.library.get_record("Eco1C1G1T1")
    custom_record = LibraryRecord(
        version="eco_augmented_blue_light",
        chassis=base_record.chassis,
        organism=base_record.organism,
        input_file=base_record.input_file,
        output_file=base_record.output_file,
        ucf_file=base_record.ucf_file,
        sensors=("BlueLight_sensor", "LacI_sensor", "AraC_sensor"),
        output_devices=base_record.output_devices,
        gate_types=base_record.gate_types,
    )
    augmented_library = pipeline.library.with_records([custom_record])
    spec = DesignSpec(
        design_name="Blue light AND biosensor",
        summary="Blue light and IPTG should drive a YFP AND circuit.",
        target_chassis="Eco",
        inputs=[
            InputSignalSpec(
                name="blue_light",
                description="Blue-light input.",
                preferred_sensor="BlueLight_sensor",
            ),
            InputSignalSpec(
                name="iptg",
                description="IPTG input.",
                preferred_sensor="LacI_sensor",
            ),
        ],
        output=OutputSignalSpec(
            name="y",
            description="YFP reporter output.",
            preferred_device="YFP_reporter",
        ),
        logic_description="AND logic.",
        verilog_module_name="blue_light_and_gate",
        verilog_code=(
            "module blue_light_and_gate\n"
            "(\n blue_light,\n iptg,\n y\n"
            ");\n\n"
            "  input blue_light;\n"
            "  input iptg;\n"
            "  output y;\n\n"
            "  assign y = blue_light & iptg;\n\n"
            "endmodule // blue_light_and_gate\n"
        ),
        selected_sensor_names=["BlueLight_sensor", "LacI_sensor"],
        selected_output_device_name="YFP_reporter",
    )

    result = pipeline.run_spec(
        spec,
        planner_name="StructuredBrief",
        library=augmented_library,
    )

    assert result.manifest.source_library_version == "eco_augmented_blue_light"
