from pathlib import Path

from ciallo_agent.config import Settings
from ciallo_agent.library import CelloLibraryIndex
from ciallo_agent.models import (
    PaperOutputDeviceCandidate,
    PaperSensorCandidate,
    PaperUCFDraft,
    UCFParameter,
)
from ciallo_agent.paper_to_ucf import PaperToUCFPipeline, load_source_text


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_load_source_text_reads_plain_text(tmp_path: Path) -> None:
    source_path = tmp_path / "paper.txt"
    source_path.write_text("Synthetic biology paper text")

    loaded = load_source_text(source_path)

    assert loaded == "Synthetic biology paper text"


def test_paper_pipeline_converts_sequence_backed_candidates_to_custom_library_spec(tmp_path: Path) -> None:
    settings = Settings(
        repo_root=REPO_ROOT,
        cello_root=REPO_ROOT / "external" / "Cello-v2",
        output_root=REPO_ROOT / "outputs" / "generated",
        openai_api_key="test-key",
        openai_model="gpt-4o-mini",
        cello_docker_image="cidarlab/cello-dnacompiler:latest",
        cello_python_env="python",
    )
    library = CelloLibraryIndex.from_repo(REPO_ROOT / "external" / "Cello-v2")
    pipeline = PaperToUCFPipeline(settings, library)
    draft = PaperUCFDraft(
        paper_title="Blue Light Sensor Paper",
        paper_summary="A paper describing a blue-light inducible sensor and BFP reporter.",
        source_path=str(REPO_ROOT / "tmp" / "paper.txt"),
        base_library_version="Eco1C1G1T1",
        custom_input_sensors=[
            PaperSensorCandidate(
                name="BlueLight_sensor",
                inducer="blue light",
                promoter_name="pBlue",
                promoter_sequence="TTGACATATAAT",
                promoter_sequence_status="extracted",
                parameters=[
                    UCFParameter(
                        name="ymax",
                        value=8.0,
                        status="extracted",
                        rationale="Reported in the main text.",
                    ),
                    UCFParameter(
                        name="ymin",
                        value=0.2,
                        status="inferred",
                        rationale="Estimated from the dose-response figure.",
                    ),
                ],
            )
        ],
        custom_output_devices=[
            PaperOutputDeviceCandidate(
                name="BFP_reporter",
                reporter="BFP",
                cassette_name="BFP_cassette",
                cassette_sequence="ATGGTGAGCAAGGGCGAGGAG",
                cassette_sequence_status="extracted",
                unit_conversion=1.5,
                unit_conversion_status="defaulted",
            )
        ],
    )

    custom_spec, warnings = pipeline._draft_to_custom_library_spec(draft)

    assert custom_spec is not None
    assert custom_spec.base_version == "Eco1C1G1T1"
    assert custom_spec.custom_input_sensors[0].name == "BlueLight_sensor"
    assert custom_spec.custom_output_devices[0].name == "BFP_reporter"
    assert warnings == []

    result = pipeline.materialize_draft(
        draft,
        source_name="paper.txt",
        output_dir=tmp_path,
    )
    assert result.generated_ucf_file.exists()
    assert result.generated_ucf_file.read_text().find("Eco1C1G1T1_generated") != -1
    assert result.custom_library_manifest is not None
    assert Path(result.custom_library_manifest.ucf_file).exists()
