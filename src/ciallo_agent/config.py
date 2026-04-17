from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _env_path(name: str, default: Path, root: Path) -> Path:
    value = os.getenv(name)
    if not value:
        return default
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    cello_root: Path
    output_root: Path
    openai_api_key: str | None
    openai_model: str
    cello_docker_image: str
    cello_python_env: str

    @classmethod
    def from_env(cls, repo_root: Path | None = None) -> "Settings":
        root = (repo_root or Path(__file__).resolve().parents[2]).resolve()
        load_dotenv(root / ".env", override=False)
        return cls(
            repo_root=root,
            cello_root=_env_path("CELLO_ROOT", root / "external" / "Cello-v2", root).resolve(),
            output_root=_env_path(
                "CIALLO_OUTPUT_ROOT",
                root / "outputs" / "generated",
                root,
            ).resolve(),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            cello_docker_image=os.getenv(
                "CELLO_DOCKER_IMAGE",
                "cidarlab/cello-dnacompiler:latest",
            ),
            cello_python_env=os.getenv("CELLO_PYTHON_ENV", "python"),
        )
