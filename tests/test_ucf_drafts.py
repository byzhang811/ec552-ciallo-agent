import json
from pathlib import Path

from ciallo_agent.models import (
    PaperGateCandidate,
    PaperOutputDeviceCandidate,
    PaperSensorCandidate,
    PaperUCFDraft,
    UCFParameter,
)
from ciallo_agent.ucf_drafts import build_generated_ucf, build_ucf_fragment, merge_ucf_drafts


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_merge_ucf_drafts_prefers_more_complete_sequence_backed_candidates() -> None:
    request_draft = PaperUCFDraft(
        paper_title="Request-derived draft",
        paper_summary="User asked for a blue-light and IPTG circuit.",
        source_path="user_request.txt",
        base_library_version="Eco1C1G1T1",
        target_chassis="Eco",
        custom_input_sensors=[
            PaperSensorCandidate(
                name="BlueLight_sensor",
                inducer="blue light",
                promoter_name="pBlue",
                promoter_sequence=None,
                promoter_sequence_status="missing",
                parameters=[
                    UCFParameter(
                        name="ymax",
                        value=10.0,
                        status="inferred",
                        rationale="User requested a strong induction profile.",
                    )
                ],
                evidence=["The request mentions blue light as an input."],
            )
        ],
        custom_output_devices=[
            PaperOutputDeviceCandidate(
                name="YFP_reporter",
                reporter="YFP",
                cassette_name="yfp_cassette",
                cassette_sequence=None,
                cassette_sequence_status="missing",
                input_count=2,
            )
        ],
    )
    source_draft = PaperUCFDraft(
        paper_title="Blue-light paper",
        paper_summary="A paper with a blue-light sensor and promoter sequence.",
        source_path="paper.pdf",
        base_library_version="Eco1C1G1T1",
        source_organism="Escherichia coli",
        custom_input_sensors=[
            PaperSensorCandidate(
                name="BlueLight_sensor",
                inducer="blue light",
                promoter_name="pBlue",
                promoter_sequence="TTGACATATAAT",
                promoter_sequence_status="extracted",
                parameters=[
                    UCFParameter(
                        name="ymin",
                        value=0.1,
                        status="extracted",
                        rationale="Reported in the paper.",
                    )
                ],
                evidence=["Promoter sequence reported in the supplementary table."],
            )
        ],
    )

    merged = merge_ucf_drafts([request_draft, source_draft])

    assert merged.custom_input_sensors[0].promoter_sequence == "TTGACATATAAT"
    assert merged.custom_input_sensors[0].promoter_sequence_status == "extracted"
    assert {parameter.name for parameter in merged.custom_input_sensors[0].parameters} == {
        "ymax",
        "ymin",
    }
    assert merged.target_chassis == "Eco"
    assert merged.source_organism == "Escherichia coli"


def test_build_ucf_fragment_emits_gate_model_structure_and_function_entries() -> None:
    draft = PaperUCFDraft(
        paper_title="Gate draft",
        paper_summary="A NOR gate draft.",
        source_path="gate.txt",
        base_library_version="Eco1C1G1T1",
        candidate_gates=[
            PaperGateCandidate(
                name="BlueNOR_gate",
                gate_type="NOR",
                regulator="BlueR",
                output_promoter_name="pBlueOut",
                output_promoter_sequence="TTGACATATAAT",
                output_promoter_sequence_status="extracted",
                response_function="Hill_response",
                parameters=[
                    UCFParameter(
                        name="ymax",
                        value=5.0,
                        status="extracted",
                        rationale="Measured.",
                    ),
                    UCFParameter(
                        name="K",
                        value=0.2,
                        status="inferred",
                        rationale="Estimated from figure.",
                    ),
                ],
            )
        ],
    )

    fragment = build_ucf_fragment(draft)
    collections = [item["collection"] for item in fragment]

    assert "gates" in collections
    assert "models" in collections
    assert "structures" in collections
    assert "functions" in collections
    assert "parts" in collections
    gate_entry = next(item for item in fragment if item["collection"] == "gates")
    assert gate_entry["name"] == "BlueNOR_gate"
    part_entry = next(item for item in fragment if item["collection"] == "parts")
    assert part_entry["name"] == "pBlueOut"


def test_build_generated_ucf_merges_fragment_into_base_library() -> None:
    base_ucf_path = (
        REPO_ROOT
        / "external"
        / "Cello-v2"
        / "sample-input"
        / "ucf"
        / "files"
        / "v2"
        / "ucf"
        / "Eco"
        / "Eco1C1G1T1.UCF.json"
    )
    base_ucf_items = json.loads(base_ucf_path.read_text())
    draft = PaperUCFDraft(
        paper_title="Generated UCF",
        paper_summary="A small draft with one custom gate.",
        source_path="gate.txt",
        base_library_version="Eco1C1G1T1",
        candidate_gates=[
            PaperGateCandidate(
                name="BlueNOR_gate",
                gate_type="NOR",
                regulator="BlueR",
                output_promoter_name="pBlueOut",
                output_promoter_sequence="TTGACATATAAT",
                output_promoter_sequence_status="extracted",
                response_function="Hill_response",
                parameters=[
                    UCFParameter(
                        name="ymax",
                        value=5.0,
                        status="extracted",
                        rationale="Measured.",
                    )
                ],
            )
        ],
    )

    generated = build_generated_ucf(
        base_ucf_items,
        draft,
        version="Eco1C1G1T1_generated",
        description="Generated UCF draft",
    )

    header = next(item for item in generated if item.get("collection") == "header")
    gate_names = {
        item["name"]
        for item in generated
        if isinstance(item, dict) and item.get("collection") == "gates"
    }

    assert header["version"] == "Eco1C1G1T1_generated"
    assert "BlueNOR_gate" in gate_names
