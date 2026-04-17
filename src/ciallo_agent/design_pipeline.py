from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .custom_library import build_library_record_from_manifest
from .library import CelloLibraryIndex
from .paper_to_ucf import PaperToUCFPipeline, PaperToUCFResult
from .pipeline import CialloPipeline, PipelineResult
from .ucf_drafts import dedupe_strings, merge_ucf_drafts


def _slugify(text: str) -> str:
    chars = [character.lower() if character.isalnum() else "_" for character in text]
    slug = "".join(chars).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "design_session"


@dataclass
class DesignFromSourcesResult:
    pipeline_result: PipelineResult
    request_result: PaperToUCFResult
    source_result: PaperToUCFResult | None
    merged_result: PaperToUCFResult
    augmented_library_version: str | None


class DesignFromSourcesPipeline:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.pipeline = CialloPipeline(self.settings)
        self.paper_pipeline = PaperToUCFPipeline(self.settings, self.pipeline.library)

    def run(
        self,
        user_request: str,
        *,
        source_file: Path | None = None,
        output_dir: Path | None = None,
        base_version: str = "Eco1C1G1T1",
        max_source_chars: int = 60000,
        force_heuristic: bool = False,
        execute_cello: bool = False,
    ) -> DesignFromSourcesResult:
        session_root = output_dir or (
            self.settings.output_root / "design_sessions" / _slugify(user_request[:80])
        )
        session_root.mkdir(parents=True, exist_ok=True)

        active_library: CelloLibraryIndex = self.pipeline.library
        request_result = self.paper_pipeline.run_text(
            source_name="user_request.txt",
            source_text=user_request,
            output_dir=session_root / "request_artifacts",
            base_version=base_version,
            author_custom_library=source_file is None,
            request_context=user_request,
            run_name="request_text",
        )
        source_result: PaperToUCFResult | None = None
        merged_result = request_result
        augmented_library_version: str | None = None

        if source_file is not None:
            source_result = self.paper_pipeline.run(
                source_file,
                output_dir=session_root / "source_artifacts",
                base_version=base_version,
                max_chars=max_source_chars,
                author_custom_library=False,
                request_context=user_request,
            )
            merged_draft = merge_ucf_drafts(
                [request_result.draft, source_result.draft],
                title="Merged request and source UCF draft",
                source_label=f"user_request + {source_file}",
            )
            merged_result = self.paper_pipeline.materialize_draft(
                merged_draft,
                source_name=f"user_request + {source_file}",
                output_dir=session_root / "knowledge_bundle",
                run_name="merged_knowledge",
                author_custom_library=True,
            )

        if merged_result.custom_library_manifest is not None:
            custom_record = build_library_record_from_manifest(
                merged_result.custom_library_manifest,
                self.pipeline.library,
            )
            active_library = active_library.with_records([custom_record])
            augmented_library_version = custom_record.version

        pipeline_result = self.pipeline.run(
            user_request,
            output_dir=session_root / "design_bundle",
            force_heuristic=force_heuristic,
            execute_cello=execute_cello,
            library=active_library,
        )

        pipeline_result.manifest.warnings.extend(request_result.warnings)
        if source_result is not None:
            pipeline_result.manifest.warnings.extend(source_result.warnings)
        if merged_result is not request_result:
            pipeline_result.manifest.warnings.extend(merged_result.warnings)
        pipeline_result.manifest.warnings = dedupe_strings(pipeline_result.manifest.warnings)

        return DesignFromSourcesResult(
            pipeline_result=pipeline_result,
            request_result=request_result,
            source_result=source_result,
            merged_result=merged_result,
            augmented_library_version=augmented_library_version,
        )
