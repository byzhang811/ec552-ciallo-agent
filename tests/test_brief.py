from pathlib import Path

from ciallo_agent.brief import compile_design_brief, load_design_brief
from ciallo_agent.library import CelloLibraryIndex
from ciallo_agent.pipeline import CialloPipeline
from ciallo_agent.validation import validate_bundle


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_compile_design_brief_maps_signals_to_local_library() -> None:
    brief = load_design_brief(REPO_ROOT / "data" / "examples" / "design_brief.json")
    library = CelloLibraryIndex.from_repo(REPO_ROOT / "external" / "Cello-v2")

    spec = compile_design_brief(brief, library)

    assert spec.selected_sensor_names == ["AraC_sensor", "LacI_sensor"]
    assert spec.selected_output_device_name == "YFP_reporter"
    assert "assign y = arabinose & iptg;" in spec.verilog_code


def test_compile_brief_pipeline_generates_schema_valid_bundle(tmp_path: Path) -> None:
    pipeline = CialloPipeline()
    brief = load_design_brief(REPO_ROOT / "data" / "examples" / "design_brief.json")
    spec = compile_design_brief(brief, pipeline.library)

    result = pipeline.run_spec(spec, output_dir=tmp_path, planner_name="StructuredBrief")
    issues = validate_bundle(result.manifest, pipeline.settings.cello_root)

    assert issues == []
    assert result.manifest.selected_sensors == ["AraC_sensor", "LacI_sensor"]
    assert result.manifest.selected_output_device == "YFP_reporter"
