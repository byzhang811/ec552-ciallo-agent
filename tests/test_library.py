from pathlib import Path

from ciallo_agent.library import CelloLibraryIndex, LibraryRecord


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_library_index_loads_official_cello_records() -> None:
    index = CelloLibraryIndex.from_repo(REPO_ROOT / "external" / "Cello-v2")
    assert index.records
    assert any(record.version == "Eco1C1G1T1" for record in index.records)


def test_choose_record_prefers_augmented_library_when_it_matches_requested_sensor() -> None:
    index = CelloLibraryIndex.from_repo(REPO_ROOT / "external" / "Cello-v2")
    custom_record = LibraryRecord(
        version="eco_augmented_blue_light",
        chassis="Eco",
        organism="Escherichia coli",
        input_file=Path("/tmp/custom.input.json"),
        output_file=Path("/tmp/custom.output.json"),
        ucf_file=Path("/tmp/custom.UCF.json"),
        sensors=("BlueLight_sensor", "AraC_sensor", "LacI_sensor"),
        output_devices=("YFP_reporter",),
        gate_types=("NOR",),
    )

    augmented = index.with_records([custom_record])
    chosen = augmented.choose_record(
        "Eco",
        required_sensor_count=2,
        preferred_sensors=["BlueLight_sensor", "LacI_sensor"],
        preferred_output_device="YFP_reporter",
    )

    assert chosen.version == "eco_augmented_blue_light"
