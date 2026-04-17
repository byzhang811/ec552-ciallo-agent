from pathlib import Path

from ciallo_agent.library import CelloLibraryIndex
from ciallo_agent.models import DesignSpec, InputSignalSpec, OutputSignalSpec
from ciallo_agent.planner import normalize_design_spec


REPO_ROOT = Path(__file__).resolve().parents[1]


def _library() -> CelloLibraryIndex:
    return CelloLibraryIndex.from_repo(REPO_ROOT / "external" / "Cello-v2")


def test_normalize_design_spec_repairs_unsupported_library_choices() -> None:
    raw = DesignSpec(
        design_name="Blue light and arabinose reporter",
        summary="Turn on fluorescence when blue light and arabinose are both present.",
        target_chassis="Eco",
        inputs=[
            InputSignalSpec(
                name="blue light",
                description="Blue light input",
                preferred_sensor="BlueLight_sensor",
            ),
            InputSignalSpec(
                name="ara",
                description="Arabinose input",
                preferred_sensor="AraC_sensor",
            ),
        ],
        output=OutputSignalSpec(
            name="fluorescent output",
            description="Fluorescent reporter",
            preferred_device="BFP_reporter",
        ),
        logic_description="Two-input AND gate",
        verilog_module_name="bad name!",
        verilog_code="",
        selected_sensor_names=["BlueLight_sensor", "AraC_sensor"],
        selected_output_device_name="BFP_reporter",
        constraints=[],
        custom_part_requests=[],
        validation_checks=[],
        manual_review_notes=[],
    )

    normalized = normalize_design_spec(
        raw,
        _library(),
        "Design a 2-input AND biosensor for blue light and arabinose in E. coli.",
    )

    assert normalized.target_chassis == "Eco"
    assert normalized.selected_output_device_name == "YFP_reporter"
    assert "AraC_sensor" in normalized.selected_sensor_names
    assert any(item.name == "BlueLight_sensor" for item in normalized.custom_part_requests)
    assert any("BlueLight_sensor" in note for note in normalized.manual_review_notes)
    assert "module" in normalized.verilog_code
    assert "assign" in normalized.verilog_code


def test_normalize_design_spec_keeps_usable_verilog_signature() -> None:
    raw = DesignSpec(
        design_name="Simple AND",
        summary="Simple AND example.",
        target_chassis="Eco",
        inputs=[
            InputSignalSpec(name="input one", description="First input", preferred_sensor="LacI_sensor"),
            InputSignalSpec(name="input two", description="Second input", preferred_sensor="AraC_sensor"),
        ],
        output=OutputSignalSpec(name="out", description="Reporter output", preferred_device="YFP_reporter"),
        logic_description="AND gate",
        verilog_module_name="should_be_overwritten",
        verilog_code=(
            "module demo_and(a, b, y);\n"
            "  input a;\n"
            "  input b;\n"
            "  output y;\n"
            "  assign y = a & b;\n"
            "endmodule\n"
        ),
        selected_sensor_names=["LacI_sensor", "AraC_sensor"],
        selected_output_device_name="YFP_reporter",
        constraints=[],
        custom_part_requests=[],
        validation_checks=[],
        manual_review_notes=[],
    )

    normalized = normalize_design_spec(
        raw,
        _library(),
        "Design a 2-input AND biosensor using arabinose and IPTG.",
    )

    assert normalized.verilog_module_name == "demo_and"
    assert [item.name for item in normalized.inputs] == ["a", "b"]
    assert normalized.output.name == "y"
    assert "assign y = a & b;" in normalized.verilog_code
