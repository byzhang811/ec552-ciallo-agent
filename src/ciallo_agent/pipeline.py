from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .cello_runner import CelloExecutionResult, CelloRunner
from .config import Settings
from .generator import ArtifactGenerator
from .library import CelloLibraryIndex
from .models import ArtifactManifest, DesignSpec
from .planner import HeuristicPlanner, OpenAIPlanner, build_planner
from .validation import validate_bundle


@dataclass
class PipelineResult:
    planner_name: str
    spec: DesignSpec
    manifest: ArtifactManifest
    validation_issues: list[str]
    cello_command: str
    execution_result: CelloExecutionResult | None
    execution_error: str | None


class CialloPipeline:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.library = CelloLibraryIndex.from_repo(self.settings.cello_root)
        self.generator = ArtifactGenerator(
            repo_root=self.settings.repo_root,
            library=self.library,
            cello_root=self.settings.cello_root,
        )
        self.runner = CelloRunner(self.settings)

    def run(
        self,
        user_request: str,
        output_dir: Path | None = None,
        *,
        force_heuristic: bool = False,
        execute_cello: bool = False,
        library: CelloLibraryIndex | None = None,
    ) -> PipelineResult:
        active_library = library or self.library
        planner = build_planner(self.settings, force_heuristic=force_heuristic)
        planner_name = planner.__class__.__name__
        planner_warnings: list[str] = []

        try:
            spec = planner.plan(user_request, active_library)
        except Exception as exc:  # noqa: BLE001
            if isinstance(planner, OpenAIPlanner):
                planner = HeuristicPlanner()
                planner_name = planner.__class__.__name__
                planner_warnings.append(
                    f"OpenAI planner failed and the pipeline fell back to the heuristic planner: {exc}"
                )
                spec = planner.plan(user_request, active_library)
            else:
                raise

        return self.run_spec(
            spec,
            output_dir=output_dir,
            execute_cello=execute_cello,
            planner_name=planner_name,
            planner_warnings=planner_warnings,
            library=active_library,
        )

    def run_spec(
        self,
        spec: DesignSpec,
        *,
        output_dir: Path | None = None,
        execute_cello: bool = False,
        planner_name: str = "StructuredInput",
        planner_warnings: list[str] | None = None,
        library: CelloLibraryIndex | None = None,
    ) -> PipelineResult:
        manifest = self.generator.generate_bundle(
            spec,
            output_root=output_dir or self.settings.output_root,
            library=library,
        )
        manifest.warnings.extend(planner_warnings or [])
        manifest_path = Path(manifest.run_directory) / "manifest.json"
        manifest_path.write_text(json.dumps(manifest.model_dump(), indent=2) + "\n")
        validation_issues = validate_bundle(manifest, self.settings.cello_root)
        command = self.runner.command_as_shell(manifest)

        execution_result = None
        execution_error = None
        if execute_cello and not validation_issues:
            try:
                execution_result = self.runner.run(manifest)
            except Exception as exc:  # noqa: BLE001
                execution_error = str(exc)

        return PipelineResult(
            planner_name=planner_name,
            spec=spec,
            manifest=manifest,
            validation_issues=validation_issues,
            cello_command=command,
            execution_result=execution_result,
            execution_error=execution_error,
        )
