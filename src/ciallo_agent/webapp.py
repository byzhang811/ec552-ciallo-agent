from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .brief import compile_design_brief
from .config import Settings
from .custom_library import build_library_record_from_manifest
from .design_pipeline import DesignFromSourcesPipeline
from .library import CelloLibraryIndex
from .models import DesignBrief, PaperUCFDraft
from .paper_to_ucf import PaperToUCFPipeline
from .pipeline import CialloPipeline
from .ucf_diff import build_ucf_diff


SCENARIO_PRESETS: list[dict[str, Any]] = [
    {
        "id": "pure_nl",
        "title": "Freeform Request",
        "badge": "LLM",
        "description": "Describe the logic, inputs, and outputs in plain language. The studio turns it into a design bundle and uses the official library when it fits.",
        "prompt": "Design a 2-input AND biosensor that turns on YFP only when arabinose and IPTG are both present.",
    },
    {
        "id": "paper_assisted",
        "title": "Paper-Assisted Drafting",
        "badge": "Paper",
        "description": "Combine a request with a paper or PDF. The studio extracts useful evidence and folds it into the design bundle.",
        "prompt": "Use the paper to help design an E. coli YFP logic circuit and reuse any supported sensors, proteins, promoters, and gates you can identify.",
    },
    {
        "id": "custom_components",
        "title": "Custom Components",
        "badge": "Draft",
        "description": "Provide a custom fragment only when the official library is not enough.",
        "prompt": "Author a custom fragment for a new blue-light sensor and a fluorescent reporter.",
    },
    {
        "id": "official_quick_design",
        "title": "Official Library Fast Track",
        "badge": "Brief",
        "description": "Compile a structured brief into Verilog, input/output files, and an official-library bundle for a quick baseline.",
        "prompt": "Quickly compile a structured brief into an official-library Cello design.",
    },
]


def _assets_dir() -> Path:
    return Path(__file__).with_name("web_assets")


def _slugify(text: str, fallback: str = "studio_run") -> str:
    chars = [character.lower() if character.isalnum() else "_" for character in text]
    slug = "".join(chars).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or fallback


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _path_is_allowed(path: Path, roots: list[Path]) -> bool:
    resolved = path.resolve()
    return any(
        resolved == root.resolve() or root.resolve() in resolved.parents
        for root in roots
    )


def _safe_file_response(path: Path, settings: Settings) -> FileResponse:
    allowed_roots = [
        settings.repo_root,
        settings.output_root,
        settings.cello_root,
    ]
    if not _path_is_allowed(path, allowed_roots):
        raise HTTPException(status_code=403, detail="The requested file is outside the allowed workspace roots.")
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    return FileResponse(path)


def _serialize_library_records(library: CelloLibraryIndex) -> list[dict[str, Any]]:
    return [
        {
            "version": record.version,
            "chassis": record.chassis,
            "organism": record.organism,
            "sensor_count": len(record.sensors),
            "output_device_count": len(record.output_devices),
            "gate_count": len(record.gate_types),
            "summary_line": record.summary_line(),
        }
        for record in library.records
    ]


def _bootstrap_payload(settings: Settings, library: CelloLibraryIndex) -> dict[str, Any]:
    default_base_version = next(
        (record.version for record in library.records if record.version == "Eco1C1G1T1"),
        library.records[0].version,
    )
    return {
        "title": "Ciallo Studio",
        "subtitle": "A local workspace for turning requests into design bundles and running official-library Cello jobs.",
        "scenario_presets": SCENARIO_PRESETS,
        "library_records": _serialize_library_records(library),
        "repo_root": str(settings.repo_root),
        "cello_root": str(settings.cello_root),
        "default_base_version": default_base_version,
        "default_request_text": SCENARIO_PRESETS[-1]["prompt"],
        "default_brief": {
            "design_name": "arabinose_iptg_and_biosensor",
            "summary": "A 2-input AND biosensor that turns on YFP only when arabinose and IPTG are both present.",
            "target_chassis": "Eco",
            "logic_operator": "AND",
            "input_signals": [
                {
                    "logical_name": "arabinose",
                    "description": "Arabinose input signal.",
                    "signal_name": "arabinose",
                    "preferred_sensor": "AraC_sensor",
                },
                {
                    "logical_name": "iptg",
                    "description": "IPTG input signal.",
                    "signal_name": "IPTG",
                    "preferred_sensor": "LacI_sensor",
                },
            ],
            "output_signal": {
                "logical_name": "yfp",
                "description": "Fluorescent YFP reporter output.",
                "signal_name": "YFP",
                "preferred_device": "YFP_reporter",
            },
            "constraints": ["Prefer the official Eco library when possible.", "Keep the design compact."],
            "notes": [],
        },
        "default_custom_draft": {
            "paper_title": "User-authored custom fragment",
            "paper_summary": "A manually curated custom gate or sensor draft from the design studio.",
            "source_path": "user_custom_fragment.json",
            "base_library_version": default_base_version,
            "target_chassis": "Eco",
            "source_organism": "Escherichia coli",
            "custom_input_sensors": [
                {
                    "name": "BlueLight_sensor",
                    "inducer": "blue light",
                    "promoter_name": "pBlue",
                    "promoter_sequence": "TTGACATATAAT",
                    "promoter_sequence_status": "extracted",
                    "response_function": "sensor_response",
                    "parameters": [
                        {
                            "name": "ymax",
                            "value": 8.0,
                            "status": "inferred",
                            "rationale": "Draft default used by the studio.",
                        }
                    ],
                    "evidence": ["Template blue-light sensor generated by the studio."],
                }
            ],
            "custom_output_devices": [
                {
                    "name": "YFP_reporter",
                    "reporter": "YFP",
                    "cassette_name": "YFP_cassette",
                    "cassette_sequence": "ATGGTGAGCAAGGGCGAGGAG",
                    "cassette_sequence_status": "extracted",
                    "unit_conversion": 1.0,
                    "unit_conversion_status": "defaulted",
                    "input_count": 2,
                    "evidence": ["Template fluorescent reporter generated by the studio."],
                }
            ],
            "candidate_gates": [
                {
                    "name": "BlueNOR_gate",
                    "gate_type": "NOR",
                    "regulator": "BlueR",
                    "output_promoter_name": "pBlueOut",
                    "output_promoter_sequence": "TTGACATATAAT",
                    "output_promoter_sequence_status": "extracted",
                    "response_function": "Hill_response",
                    "parameters": [
                        {
                            "name": "ymax",
                            "value": 5.0,
                            "status": "inferred",
                            "rationale": "Draft default used by the studio.",
                        }
                    ],
                    "evidence": ["Template NOR gate generated by the studio."],
                }
            ],
            "missing_information": ["No publication evidence yet.", "Sequence and parameter defaults may need review."],
            "inference_notes": ["Studio template generated locally."],
            "warnings": ["This template is intended for visual editing and quick demos."],
        },
    }


def _load_ucf_json(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text())


def _selected_base_version(result: Any, default: str) -> str:
    for candidate in (
        getattr(result, "merged_result", None),
        getattr(result, "source_result", None),
        getattr(result, "request_result", None),
    ):
        if candidate is None:
            continue
        draft = getattr(candidate, "draft", None)
        if draft is not None and getattr(draft, "base_library_version", None):
            return draft.base_library_version
    return default


def _manifest_from_result(result: Any) -> Any | None:
    manifest = getattr(result, "manifest", None)
    if manifest is not None:
        return manifest
    pipeline_result = getattr(result, "pipeline_result", None)
    if pipeline_result is not None:
        return getattr(pipeline_result, "manifest", None)
    return None


def _library_extension_needed(result: Any) -> tuple[bool, list[str]]:
    spec = getattr(getattr(result, "pipeline_result", None), "spec", None)
    if spec is None:
        return False, []
    reasons: list[str] = []

    if getattr(spec, "custom_part_requests", None):
        reasons.append(
            "This request references parts that are not present in the official local library."
        )

    for note in getattr(spec, "manual_review_notes", []) or []:
        lowered = note.lower()
        if (
            "not present in the official local library" in lowered
            or "only provides" in lowered
            or "needs a library extension" in lowered
            or "falling back to" in lowered and "official local library" in lowered
        ):
            reasons.append(note)

    warnings = getattr(getattr(result, "manifest", None), "warnings", []) or []
    for warning in warnings:
        lowered = warning.lower()
        if "custom library bundle was generated" in lowered:
            reasons.append(warning)

    unique_reasons = []
    seen = set()
    for reason in reasons:
        if reason in seen:
            continue
        seen.add(reason)
        unique_reasons.append(reason)
    return bool(unique_reasons), unique_reasons


def _maybe_run_cello(
    pipeline: CialloPipeline,
    result: Any,
    *,
    requested: bool,
    extension_needed: bool,
) -> tuple[Any | None, str | None]:
    if not requested:
        return None, None
    if extension_needed:
        return None, "Official library is not sufficient for this request, so Cello execution was skipped."
    try:
        execution_result = pipeline.runner.run(result.manifest)
        return execution_result, None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _build_response_payload(
    *,
    mode: str,
    request_text: str,
    settings: Settings,
    pipeline: CialloPipeline,
    result: Any,
    generated_ucf_file: Path,
    base_version: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base_record = pipeline.library.get_record(base_version)
    base_ucf = _load_ucf_json(base_record.ucf_file)
    generated_ucf = _load_ucf_json(generated_ucf_file)
    diff = build_ucf_diff(base_ucf, generated_ucf)

    manifest = _manifest_from_result(result)
    pipeline_result = getattr(result, "pipeline_result", None)
    selected_sensors = []
    selected_output_device = None
    validation_issues: list[str] = []
    warnings: list[str] = []
    planner_name: str | None = None
    execution_result = None
    execution_error = None
    run_directory = ""
    if manifest is not None:
        selected_sensors = list(getattr(manifest, "selected_sensors", []))
        selected_output_device = getattr(manifest, "selected_output_device", None)
        warnings = list(getattr(manifest, "warnings", []))
        run_directory = str(getattr(manifest, "run_directory", ""))
    if pipeline_result is not None:
        validation_issues = list(getattr(pipeline_result, "validation_issues", []))
        planner_name = getattr(pipeline_result, "planner_name", None)
        execution_result = getattr(pipeline_result, "execution_result", None)
        execution_error = getattr(pipeline_result, "execution_error", None)
    if planner_name is None:
        planner_name = getattr(result, "planner_name", None)

    payload: dict[str, Any] = {
        "mode": mode,
        "request_text": request_text,
        "base_version": base_version,
        "base_record": {
            "version": base_record.version,
            "chassis": base_record.chassis,
            "organism": base_record.organism,
            "summary_line": base_record.summary_line(),
        },
        "result_summary": {
            "planner": planner_name,
            "run_directory": run_directory,
            "selected_sensors": selected_sensors,
            "selected_output_device": selected_output_device,
            "validation_issues": validation_issues,
            "warnings": warnings,
            "cello_ran": execution_result is not None,
            "execution_error": execution_error,
        },
        "base_ucf_path": str(base_record.ucf_file),
        "generated_ucf_path": str(generated_ucf_file),
        "base_ucf": base_ucf,
        "generated_ucf": generated_ucf,
        "ucf_diff": diff,
    }
    if manifest is not None:
        payload["design_artifacts"] = {
            "run_directory": run_directory,
            "manifest": getattr(manifest, "run_directory", ""),
            "spec": getattr(manifest, "spec_file", ""),
            "verilog": getattr(manifest, "verilog_file", ""),
            "input": getattr(manifest, "input_file", ""),
            "output": getattr(manifest, "output_file", ""),
            "options": getattr(manifest, "options_file", ""),
            "summary": getattr(manifest, "summary_file", ""),
            "cello_output": getattr(manifest, "cello_output_dir", ""),
        }
    if extra:
        payload.update(extra)
    return payload


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    pipeline = CialloPipeline(settings)
    paper_pipeline = PaperToUCFPipeline(settings, pipeline.library)
    assets_dir = _assets_dir()
    app_version = str(int((assets_dir / "app.js").stat().st_mtime))
    app_asset = f"/assets/app.js?v={app_version}"
    style_asset = f"/assets/styles.css?v={app_version}"

    app = FastAPI(title="Ciallo Studio")
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/", response_class=HTMLResponse)
    def index() -> FileResponse:
        html = (assets_dir / "index.html").read_text()
        html = html.replace("/assets/styles.css", style_asset)
        html = html.replace("/assets/app.js", app_asset)
        response = HTMLResponse(html)
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.get("/api/bootstrap")
    def bootstrap() -> JSONResponse:
        return JSONResponse(_bootstrap_payload(settings, pipeline.library))

    @app.get("/api/file")
    def get_file(path: str) -> FileResponse:
        return _safe_file_response(Path(path), settings)

    @app.post("/api/design")
    async def design(
        mode: str = Form(...),
        request_text: str = Form(""),
        base_version: str = Form("Eco1C1G1T1"),
        run_cello: bool = Form(False),
        force_heuristic: bool = Form(False),
        max_source_chars: int = Form(60000),
        brief_json: str = Form(""),
        custom_draft_json: str = Form(""),
        source_file: UploadFile | None = File(None),
    ) -> JSONResponse:
        session_root = settings.output_root / "studio_sessions"
        session_root.mkdir(parents=True, exist_ok=True)

        source_path: Path | None = None
        temp_dir: tempfile.TemporaryDirectory[str] | None = None
        if source_file is not None and source_file.filename:
            temp_dir = tempfile.TemporaryDirectory(prefix="ciallo-studio-")
            source_path = Path(temp_dir.name) / source_file.filename
            source_path.write_bytes(await source_file.read())

        try:
            if mode == "official_quick_design":
                if not brief_json.strip():
                    raise HTTPException(
                        status_code=400,
                        detail="official_quick_design mode requires brief_json.",
                    )
                brief = DesignBrief.model_validate_json(brief_json)
                spec = compile_design_brief(brief, pipeline.library)
                result = pipeline.run_spec(
                    spec,
                    output_dir=session_root / "brief_runs",
                    execute_cello=False,
                    planner_name="StructuredBrief",
                    library=pipeline.library,
                )
                extension_needed, extension_reasons = _library_extension_needed(result)
                execution_result, execution_error = _maybe_run_cello(
                    pipeline,
                    result,
                    requested=run_cello,
                    extension_needed=extension_needed,
                )
                result.execution_result = execution_result
                result.execution_error = execution_error
                generated_ucf_file = Path(result.manifest.ucf_file)
                response = _build_response_payload(
                    mode=mode,
                    request_text=request_text or brief.summary,
                    settings=settings,
                    pipeline=pipeline,
                    result=result,
                    generated_ucf_file=generated_ucf_file,
                    base_version=result.manifest.source_library_version,
                    extra={
                        "library_status": {
                            "sufficient": not extension_needed,
                            "reasons": extension_reasons,
                        },
                        "brief": json.loads(brief.model_dump_json()),
                        "spec": json.loads(spec.model_dump_json()),
                        "artifacts": {
                            "manifest": result.manifest.run_directory + "/manifest.json",
                            "spec": result.manifest.run_directory + "/design_spec.json",
                            "input": result.manifest.input_file,
                            "output": result.manifest.output_file,
                            "ucf": result.manifest.ucf_file,
                            "summary": result.manifest.summary_file,
                            "cello_output": result.manifest.cello_output_dir,
                        },
                    },
                )
                return JSONResponse(response)

            if mode == "custom_components":
                if not custom_draft_json.strip():
                    raise HTTPException(
                        status_code=400,
                        detail="custom_components mode requires custom_draft_json.",
                    )
                draft = PaperUCFDraft.model_validate_json(custom_draft_json)
                custom_result = paper_pipeline.materialize_draft(
                    draft,
                    source_name=draft.source_path or "custom_components",
                    output_dir=session_root / "custom_components",
                    run_name=_slugify(draft.paper_title, "custom_components"),
                    author_custom_library=True,
                )
                active_library = pipeline.library
                if custom_result.custom_library_manifest is not None:
                    custom_record = build_library_record_from_manifest(
                        custom_result.custom_library_manifest,
                        pipeline.library,
                    )
                    active_library = pipeline.library.with_records([custom_record])
                request_for_design = request_text or draft.paper_summary or draft.paper_title
                design_result = pipeline.run(
                    request_for_design,
                    output_dir=session_root / "custom_design",
                    force_heuristic=force_heuristic,
                    execute_cello=False,
                    library=active_library,
                )
                extension_needed, extension_reasons = _library_extension_needed(design_result)
                execution_result, execution_error = _maybe_run_cello(
                    pipeline,
                    design_result,
                    requested=run_cello,
                    extension_needed=extension_needed,
                )
                design_result.execution_result = execution_result
                design_result.execution_error = execution_error
                generated_ucf_file = custom_result.generated_ucf_file
                response = _build_response_payload(
                    mode=mode,
                    request_text=request_for_design,
                    settings=settings,
                    pipeline=pipeline,
                    result=design_result,
                    generated_ucf_file=generated_ucf_file,
                    base_version=draft.base_library_version,
                    extra={
                        "library_status": {
                            "sufficient": not extension_needed,
                            "reasons": extension_reasons,
                        },
                        "custom_draft": json.loads(draft.model_dump_json()),
                        "custom_manifest": json.loads(custom_result.custom_library_manifest.model_dump_json())
                        if custom_result.custom_library_manifest is not None
                        else None,
                        "paper_artifacts": {
                            "draft_file": str(custom_result.draft_file),
                            "summary_file": str(custom_result.summary_file),
                            "generated_ucf_file": str(custom_result.generated_ucf_file),
                            "input_sensor_draft_file": str(custom_result.input_sensor_draft_file),
                            "output_device_draft_file": str(custom_result.output_device_draft_file),
                            "ucf_fragment_file": str(custom_result.ucf_fragment_file),
                        },
                    },
                )
                return JSONResponse(response)

            if mode == "paper_assisted":
                if source_path is None:
                    raise HTTPException(
                        status_code=400,
                        detail="paper_assisted mode requires a source_file upload.",
                    )
                design_pipeline = DesignFromSourcesPipeline(settings)
                design_result = design_pipeline.run(
                    request_text or source_path.stem,
                    source_file=source_path,
                    output_dir=session_root / "paper_runs",
                    base_version=base_version,
                    max_source_chars=max_source_chars,
                    force_heuristic=force_heuristic,
                    execute_cello=False,
                )
                extension_needed, extension_reasons = _library_extension_needed(design_result)
                execution_result, execution_error = _maybe_run_cello(
                    design_pipeline.pipeline,
                    design_result,
                    requested=run_cello,
                    extension_needed=extension_needed,
                )
                design_result.pipeline_result.execution_result = execution_result
                design_result.pipeline_result.execution_error = execution_error
                generated_ucf = (
                    design_result.merged_result.generated_ucf_file
                    if design_result.source_result is not None
                    else design_result.request_result.generated_ucf_file
                )
                response = _build_response_payload(
                    mode=mode,
                    request_text=request_text or source_path.stem,
                    settings=settings,
                    pipeline=design_pipeline.pipeline,
                    result=design_result,
                    generated_ucf_file=generated_ucf,
                    base_version=_selected_base_version(design_result, base_version),
                    extra={
                        "library_status": {
                            "sufficient": not extension_needed,
                            "reasons": extension_reasons,
                        },
                        "request_artifacts": {
                            "draft_file": str(design_result.request_result.draft_file),
                            "summary_file": str(design_result.request_result.summary_file),
                            "generated_ucf_file": str(design_result.request_result.generated_ucf_file),
                            "input_sensor_draft_file": str(design_result.request_result.input_sensor_draft_file),
                            "output_device_draft_file": str(design_result.request_result.output_device_draft_file),
                            "ucf_fragment_file": str(design_result.request_result.ucf_fragment_file),
                        },
                        "source_artifacts": (
                            {
                                "draft_file": str(design_result.source_result.draft_file),
                                "summary_file": str(design_result.source_result.summary_file),
                                "generated_ucf_file": str(design_result.source_result.generated_ucf_file),
                                "input_sensor_draft_file": str(design_result.source_result.input_sensor_draft_file),
                                "output_device_draft_file": str(design_result.source_result.output_device_draft_file),
                                "ucf_fragment_file": str(design_result.source_result.ucf_fragment_file),
                            }
                            if design_result.source_result is not None
                            else None
                        ),
                        "merged_artifacts": {
                            "draft_file": str(design_result.merged_result.draft_file),
                            "summary_file": str(design_result.merged_result.summary_file),
                            "generated_ucf_file": str(design_result.merged_result.generated_ucf_file),
                            "input_sensor_draft_file": str(design_result.merged_result.input_sensor_draft_file),
                            "output_device_draft_file": str(design_result.merged_result.output_device_draft_file),
                            "ucf_fragment_file": str(design_result.merged_result.ucf_fragment_file),
                        },
                    },
                )
                return JSONResponse(response)

            # default pure natural language flow
            design_pipeline = DesignFromSourcesPipeline(settings)
            design_result = design_pipeline.run(
                request_text,
                output_dir=session_root / "nl_runs",
                base_version=base_version,
                force_heuristic=force_heuristic,
                execute_cello=False,
            )
            extension_needed, extension_reasons = _library_extension_needed(design_result)
            execution_result, execution_error = _maybe_run_cello(
                design_pipeline.pipeline,
                design_result,
                requested=run_cello,
                extension_needed=extension_needed,
            )
            design_result.pipeline_result.execution_result = execution_result
            design_result.pipeline_result.execution_error = execution_error
            generated_ucf = design_result.request_result.generated_ucf_file
            response = _build_response_payload(
                mode="pure_nl",
                request_text=request_text,
                settings=settings,
                pipeline=design_pipeline.pipeline,
                result=design_result,
                generated_ucf_file=generated_ucf,
                base_version=_selected_base_version(design_result, base_version),
                extra={
                    "library_status": {
                        "sufficient": not extension_needed,
                        "reasons": extension_reasons,
                    },
                    "request_artifacts": {
                        "draft_file": str(design_result.request_result.draft_file),
                        "summary_file": str(design_result.request_result.summary_file),
                        "generated_ucf_file": str(design_result.request_result.generated_ucf_file),
                        "input_sensor_draft_file": str(design_result.request_result.input_sensor_draft_file),
                        "output_device_draft_file": str(design_result.request_result.output_device_draft_file),
                        "ucf_fragment_file": str(design_result.request_result.ucf_fragment_file),
                    },
                },
            )
            return JSONResponse(response)
        finally:
            if temp_dir is not None:
                temp_dir.cleanup()

    return app
