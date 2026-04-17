from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import Settings
from .brief import compile_design_brief, load_design_brief
from .custom_library import CustomLibraryAuthor, load_custom_library_spec
from .design_pipeline import DesignFromSourcesPipeline
from .paper_to_ucf import PaperToUCFPipeline
from .pipeline import CialloPipeline
from .webapp import create_app
from .validation import validate_file_triplet


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ciallo Agent scaffold CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("inspect-library", help="List available official Cello libraries")

    author_parser = subparsers.add_parser(
        "author-library",
        help="Generate a custom input/output/UCF library bundle from a simplified JSON spec",
    )
    author_parser.add_argument(
        "spec_file",
        type=Path,
        help="Path to the simplified custom library JSON spec",
    )
    author_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional output directory for generated custom library bundles",
    )

    brief_parser = subparsers.add_parser(
        "compile-brief",
        help="Compile a structured design brief JSON into a Cello input bundle",
    )
    brief_parser.add_argument(
        "brief_file",
        type=Path,
        help="Path to the structured design brief JSON file",
    )
    brief_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional output directory for generated bundles",
    )
    brief_parser.add_argument(
        "--run-cello",
        action="store_true",
        help="Execute the generated bundle with Docker-based Cello after validation",
    )

    paper_parser = subparsers.add_parser(
        "paper-to-ucf",
        help="Extract a draft UCF payload from a paper or PDF using OpenAI",
    )
    paper_parser.add_argument(
        "source_file",
        type=Path,
        help="Path to a PDF, TXT, MD, or JSON source file",
    )
    paper_parser.add_argument(
        "--base-version",
        default="Eco1C1G1T1",
        help="Official local Cello library version to extend",
    )
    paper_parser.add_argument(
        "--max-chars",
        type=int,
        default=60000,
        help="Maximum number of extracted source characters to send to OpenAI",
    )
    paper_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional output directory for generated paper-to-UCF artifacts",
    )
    paper_parser.add_argument(
        "--skip-library-authoring",
        action="store_true",
        help="Only emit the extracted draft JSON and skip custom library generation",
    )
    paper_parser.add_argument(
        "--request-context",
        default=None,
        help="Optional natural-language design context to bias the source extraction",
    )

    design_parser = subparsers.add_parser(
        "design",
        help="Unified workflow: natural-language request plus optional source file",
    )
    design_parser.add_argument("request", nargs="+", help="Natural-language design request")
    design_parser.add_argument(
        "--source-file",
        type=Path,
        default=None,
        help="Optional PDF, TXT, or other source document with extra biology details",
    )
    design_parser.add_argument(
        "--base-version",
        default="Eco1C1G1T1",
        help="Official local Cello library version to extend when a source file is supplied",
    )
    design_parser.add_argument(
        "--max-source-chars",
        type=int,
        default=60000,
        help="Maximum number of source characters to send to OpenAI for source extraction",
    )
    design_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional output directory for the unified workflow artifacts",
    )
    design_parser.add_argument(
        "--force-heuristic",
        action="store_true",
        help="Skip OpenAI and use the heuristic parser only for the request-planning step",
    )
    design_parser.add_argument(
        "--run-cello",
        action="store_true",
        help="Execute the generated bundle with Docker-based Cello after validation",
    )

    serve_parser = subparsers.add_parser(
        "serve",
        help="Start the local Ciallo Studio web application",
    )
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host interface for the web server")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port for the web server")
    serve_parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable uvicorn auto-reload during development",
    )

    plan_parser = subparsers.add_parser(
        "plan",
        help="Turn natural language into a Cello input bundle",
    )
    plan_parser.add_argument("request", nargs="+", help="Natural-language design request")
    plan_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional output directory for generated bundles",
    )
    plan_parser.add_argument(
        "--force-heuristic",
        action="store_true",
        help="Skip OpenAI and use the heuristic parser only",
    )
    plan_parser.add_argument(
        "--run-cello",
        action="store_true",
        help="Execute the generated bundle with Docker-based Cello after validation",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    settings = Settings.from_env()
    pipeline = CialloPipeline(settings)

    if args.command == "inspect-library":
        for record in pipeline.library.records:
            print(record.summary_line())
        return 0

    if args.command == "author-library":
        output_root = args.output_dir or settings.output_root / "custom_libraries"
        spec = load_custom_library_spec(args.spec_file)
        author = CustomLibraryAuthor(pipeline.library, settings.cello_root)
        manifest = author.author(spec, output_root)
        issues = validate_file_triplet(
            input_path=Path(manifest.input_file),
            output_path=Path(manifest.output_file),
            ucf_path=Path(manifest.ucf_file),
            cello_root=settings.cello_root,
        )
        print(
            json.dumps(
                {
                    "library_name": manifest.library_name,
                    "run_directory": manifest.run_directory,
                    "base_library_version": manifest.base_library_version,
                    "warnings": manifest.warnings,
                    "validation_issues": issues,
                },
                indent=2,
            )
        )
        return 0

    if args.command == "compile-brief":
        brief = load_design_brief(args.brief_file)
        spec = compile_design_brief(brief, pipeline.library)
        result = pipeline.run_spec(
            spec,
            output_dir=args.output_dir,
            execute_cello=args.run_cello,
            planner_name="StructuredBrief",
        )
        print(
            json.dumps(
                {
                    "planner": result.planner_name,
                    "run_directory": result.manifest.run_directory,
                    "library_version": result.manifest.source_library_version,
                    "selected_sensors": result.manifest.selected_sensors,
                    "selected_output_device": result.manifest.selected_output_device,
                    "warnings": result.manifest.warnings,
                    "validation_issues": result.validation_issues,
                    "cello_command": result.cello_command,
                    "execution_error": result.execution_error,
                },
                indent=2,
            )
        )
        return 0

    if args.command == "paper-to-ucf":
        paper_pipeline = PaperToUCFPipeline(settings, pipeline.library)
        result = paper_pipeline.run(
            args.source_file,
            output_dir=args.output_dir,
            base_version=args.base_version,
            max_chars=args.max_chars,
            author_custom_library=not args.skip_library_authoring,
            request_context=args.request_context,
        )
        print(
            json.dumps(
                {
                    "paper_title": result.draft.paper_title,
                    "run_directory": str(result.run_directory),
                    "draft_file": str(result.draft_file),
                    "summary_file": str(result.summary_file),
                    "generated_ucf_file": str(result.generated_ucf_file),
                    "input_sensor_draft_file": str(result.input_sensor_draft_file),
                    "output_device_draft_file": str(result.output_device_draft_file),
                    "ucf_fragment_file": str(result.ucf_fragment_file),
                    "custom_library_spec_file": (
                        str(result.custom_library_spec_file)
                        if result.custom_library_spec_file is not None
                        else None
                    ),
                    "custom_library_run_directory": (
                        result.custom_library_manifest.run_directory
                        if result.custom_library_manifest is not None
                        else None
                    ),
                    "warnings": result.warnings,
                },
                indent=2,
            )
        )
        return 0

    if args.command == "design":
        design_pipeline = DesignFromSourcesPipeline(settings)
        request_text = " ".join(args.request)
        result = design_pipeline.run(
            request_text,
            source_file=args.source_file,
            output_dir=args.output_dir,
            base_version=args.base_version,
            max_source_chars=args.max_source_chars,
            force_heuristic=args.force_heuristic,
            execute_cello=args.run_cello,
        )
        summary = {
            "planner": result.pipeline_result.planner_name,
            "run_directory": result.pipeline_result.manifest.run_directory,
            "library_version": result.pipeline_result.manifest.source_library_version,
            "augmented_library_version": result.augmented_library_version,
            "selected_sensors": result.pipeline_result.manifest.selected_sensors,
            "selected_output_device": result.pipeline_result.manifest.selected_output_device,
            "warnings": result.pipeline_result.manifest.warnings,
            "validation_issues": result.pipeline_result.validation_issues,
            "cello_command": result.pipeline_result.cello_command,
            "execution_error": result.pipeline_result.execution_error,
            "request_draft_file": str(result.request_result.draft_file),
            "request_generated_ucf_file": str(result.request_result.generated_ucf_file),
            "request_ucf_fragment_file": str(result.request_result.ucf_fragment_file),
            "source_summary_file": (
                str(result.source_result.summary_file)
                if result.source_result is not None
                else None
            ),
            "source_draft_file": (
                str(result.source_result.draft_file)
                if result.source_result is not None
                else None
            ),
            "source_generated_ucf_file": (
                str(result.source_result.generated_ucf_file)
                if result.source_result is not None
                else None
            ),
            "merged_draft_file": str(result.merged_result.draft_file),
            "merged_generated_ucf_file": str(result.merged_result.generated_ucf_file),
            "merged_ucf_fragment_file": str(result.merged_result.ucf_fragment_file),
        }
        print(json.dumps(summary, indent=2))
        return 0

    if args.command == "serve":
        try:
            import uvicorn
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "uvicorn is required to run the local studio. Install the project dependencies first."
            ) from exc

        app = create_app(settings)
        uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
        return 0

    request_text = " ".join(args.request)
    result = pipeline.run(
        request_text,
        output_dir=args.output_dir,
        force_heuristic=args.force_heuristic,
        execute_cello=args.run_cello,
    )

    summary = {
        "planner": result.planner_name,
        "run_directory": result.manifest.run_directory,
        "library_version": result.manifest.source_library_version,
        "selected_sensors": result.manifest.selected_sensors,
        "selected_output_device": result.manifest.selected_output_device,
        "warnings": result.manifest.warnings,
        "validation_issues": result.validation_issues,
        "cello_command": result.cello_command,
        "execution_error": result.execution_error,
    }
    print(json.dumps(summary, indent=2))

    if result.execution_result is not None:
        execution = {
            "returncode": result.execution_result.returncode,
            "stdout": result.execution_result.stdout,
            "stderr": result.execution_result.stderr,
        }
        print(json.dumps(execution, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
