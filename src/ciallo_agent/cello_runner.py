from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .models import ArtifactManifest


@dataclass
class CelloExecutionResult:
    command: str
    returncode: int
    stdout: str
    stderr: str


class CelloRunner:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def command_as_list(self, manifest: ArtifactManifest) -> list[str]:
        run_dir = Path(manifest.run_directory)
        output_dir = Path(manifest.cello_output_dir)
        return [
            "docker",
            "run",
            "--rm",
            "-i",
            "-v",
            f"{run_dir}:/root/input",
            "-v",
            f"{output_dir}:/root/output",
            self._settings.cello_docker_image,
            "java",
            "-classpath",
            "/root/app.jar",
            "org.cellocad.v2.DNACompiler.runtime.Main",
            "-inputNetlist",
            f"/root/input/{Path(manifest.verilog_file).name}",
            "-options",
            f"/root/input/{Path(manifest.options_file).name}",
            "-userConstraintsFile",
            f"/root/input/{Path(manifest.ucf_file).name}",
            "-inputSensorFile",
            f"/root/input/{Path(manifest.input_file).name}",
            "-outputDeviceFile",
            f"/root/input/{Path(manifest.output_file).name}",
            "-pythonEnv",
            self._settings.cello_python_env,
            "-outputDir",
            "/root/output",
        ]

    def command_as_shell(self, manifest: ArtifactManifest) -> str:
        return " ".join(shlex.quote(part) for part in self.command_as_list(manifest))

    def run(self, manifest: ArtifactManifest) -> CelloExecutionResult:
        if not self._docker_ready():
            raise RuntimeError(
                "Docker daemon is not running. Start Docker Desktop before invoking Cello."
            )

        command = self.command_as_list(manifest)
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        return CelloExecutionResult(
            command=self.command_as_shell(manifest),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def _docker_ready(self) -> bool:
        probe = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            check=False,
        )
        return probe.returncode == 0
