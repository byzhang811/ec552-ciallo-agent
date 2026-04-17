from pathlib import Path

from ciallo_agent.config import Settings


def test_settings_from_env_loads_repo_dotenv_and_resolves_relative_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".env").write_text(
        "OPENAI_API_KEY=test-key\n"
        "OPENAI_MODEL=gpt-4o-mini\n"
        "CELLO_ROOT=vendor/cello\n"
        "CIALLO_OUTPUT_ROOT=generated/out\n"
    )

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("CELLO_ROOT", raising=False)
    monkeypatch.delenv("CIALLO_OUTPUT_ROOT", raising=False)

    settings = Settings.from_env(repo_root)

    assert settings.openai_api_key == "test-key"
    assert settings.openai_model == "gpt-4o-mini"
    assert settings.cello_root == (repo_root / "vendor" / "cello").resolve()
    assert settings.output_root == (repo_root / "generated" / "out").resolve()
