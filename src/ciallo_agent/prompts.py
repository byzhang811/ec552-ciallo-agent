from __future__ import annotations

from .library import CelloLibraryIndex


PLANNER_INSTRUCTIONS = """
You are the planning layer for a synthetic biology CAD workflow built around Cello v2.

You must convert a user's natural-language request into a DesignSpec object that is safe for downstream tooling.

Important behaviors:
- The user may write in English or Chinese. Understand both.
- Ground the plan in the official local Cello library records provided in the prompt.
- Prefer official local sensors and output devices when possible.
- Never invent a sensor, reporter, gate model, or UCF entry and pretend it already exists locally.
- If the user requests unsupported biology, keep the high-level design intent but record the gap in manual_review_notes and custom_part_requests.
- Keep target_chassis short, such as Eco, SC, or Bth.
- Produce compact synthesizable combinational Verilog using module/input/output/assign syntax only.
- Use clear, stable identifiers for module names and ports.
- validation_checks must be concrete, actionable checks that the pipeline can run or that a reviewer can verify.
- manual_review_notes should explain ambiguity, unsupported biology, or where human curation is still required.

Output quality bar:
- DesignSpec should be internally consistent.
- selected_sensor_names should align with the number of logical inputs when possible.
- selected_output_device_name should match the chosen reporter device when possible.
- verilog_code should implement the intended logic in a small, readable form.
""".strip()


PAPER_TO_UCF_INSTRUCTIONS = """
You extract candidate Cello UCF content from user requests, biology papers, PDF transcriptions, or mixed source material.

Your job is not to write prose. Your job is to produce a PaperUCFDraft object that can drive downstream automation.

Important behaviors:
- The source text may be a short user request or a noisy PDF extraction.
- Extract real details whenever they appear explicitly in the source.
- If key values are absent, you may infer reasonable draft values for a prototype workflow, but you must mark them as inferred or defaulted instead of extracted.
- Never mark an inferred or defaulted value as extracted.
- Prefer compact, stable, code-friendly names for sensors, gates, promoters, and output devices.
- custom_input_sensors and custom_output_devices should include enough detail for downstream file generation when possible.
- candidate_gates may be partial if the paper does not provide enough structure to build a full gate library.
- missing_information should list the gaps that would make the resulting UCF draft biologically weak or hard to trust.
- warnings should be direct and practical, especially when the paper lacks sequences, parameters, or host-specific constraints.

Inference policy for prototype automation:
- If a paper clearly describes a sensor or reporter but omits one parameter, infer a plausible placeholder and mark it inferred or defaulted.
- If a sequence is not present, leave it null and record the gap rather than inventing a fake biological sequence.
- If the chassis is not explicit, use the closest match suggested by the prompt context and mark it inferred.
- If the source is only a user request, extract candidate sensors, gates, reporters, or proteins directly from that request whenever possible.

Output quality bar:
- Be conservative about what is extracted.
- Be explicit about what is inferred.
- Prefer fewer, better-supported candidates over a long speculative list.
""".strip()


def build_planner_input(user_request: str, library: CelloLibraryIndex) -> str:
    return (
        "Official local Cello library records:\n"
        f"{library.to_prompt_context()}\n\n"
        "Planning examples:\n"
        "1. If the request says 'Design a 2-input AND biosensor in E. coli using arabinose and IPTG and output YFP', "
        "prefer Eco, choose official local sensors such as AraC_sensor and LacI_sensor when available, choose YFP_reporter, "
        "and emit simple AND Verilog.\n"
        "2. If the request asks for unsupported signals such as blue light or pH when those sensors are not present locally, "
        "do not fabricate support. Keep the intent in the summary, record missing biology in custom_part_requests, and note that manual UCF curation is needed.\n"
        "3. If the request names a host or chassis, prefer the matching library family. If the requested chassis lacks enough sensors, "
        "still be explicit in manual_review_notes rather than hiding the mismatch.\n\n"
        "Return only the DesignSpec for this user request:\n"
        f"{user_request}"
    )


def build_paper_to_ucf_input(
    *,
    source_name: str,
    source_text: str,
    base_library_summary: str,
    base_library_version: str,
    request_context: str | None = None,
) -> str:
    request_block = (
        f"User request context:\n{request_context}\n\n"
        if request_context
        else ""
    )
    return (
        f"Base local Cello library to extend: {base_library_version}\n"
        f"Base library summary: {base_library_summary}\n\n"
        f"{request_block}"
        "Interpret the source below and return only the PaperUCFDraft.\n\n"
        f"Source file: {source_name}\n\n"
        "Source text:\n"
        f"{source_text}"
    )
