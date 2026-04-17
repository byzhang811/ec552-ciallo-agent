from pathlib import Path

from ciallo_agent.custom_library import CustomLibraryAuthor, load_custom_library_spec
from ciallo_agent.library import CelloLibraryIndex
from ciallo_agent.validation import validate_file_triplet


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_author_library_generates_schema_valid_custom_files(tmp_path: Path) -> None:
    library = CelloLibraryIndex.from_repo(REPO_ROOT / "external" / "Cello-v2")
    author = CustomLibraryAuthor(library, REPO_ROOT / "external" / "Cello-v2")
    spec = load_custom_library_spec(
        REPO_ROOT / "data" / "examples" / "custom_library_request.json"
    )

    manifest = author.author(spec, tmp_path)
    issues = validate_file_triplet(
        input_path=Path(manifest.input_file),
        output_path=Path(manifest.output_file),
        ucf_path=Path(manifest.ucf_file),
        cello_root=REPO_ROOT / "external" / "Cello-v2",
    )

    assert issues == []
    input_text = Path(manifest.input_file).read_text()
    output_text = Path(manifest.output_file).read_text()
    assert "BlueLight_sensor" in input_text
    assert "BFP_reporter" in output_text
