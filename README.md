# Ciallo Agent Scaffold

This workspace now contains a first-pass scaffold for an `LLM agent -> structured spec -> Cello input bundle -> Cello validation` workflow.

The goal is to help you turn natural-language synthetic biology design requests into:

- a structured design spec
- Verilog
- a selected `input.json`
- a selected `output.json`
- a chosen base `UCF.json`
- a Docker command that can run Cello v2

The current implementation is intentionally conservative:

- it uses the official `CIDARLAB/Cello-v2` repository as the local source of truth
- it retrieves from the official sample `v2` libraries before attempting any custom UCF generation
- it validates generated JSON files against the official Cello JSON schemas
- it keeps custom UCF work as a follow-up skeleton instead of inventing invalid biological entries

## Project Layout

- `external/Cello-v2/`: official Cello v2 source tree
- `src/ciallo_agent/`: Python package for planning, retrieval, generation, validation, and execution
- `docs/architecture.md`: high-level system design
- `outputs/generated/`: generated run bundles
- `tests/`: smoke tests for the scaffold

## Quick Start

1. Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

2. Fetch the official Cello-v2 repository that the workspace uses locally:

```bash
bash scripts/bootstrap_cello.sh
```

3. Inspect the bundled official Cello libraries:

```bash
python -m ciallo_agent.cli inspect-library
```

4. Generate the same bundle from a structured template instead of free-form natural language:

```bash
python -m ciallo_agent.cli compile-brief data/examples/design_brief.json
```

5. Generate a run bundle from natural language:

```bash
python -m ciallo_agent.cli plan "Design a 2-input AND biosensor that turns on YFP only when arabinose and IPTG are both present."
```

6. Run the unified workflow with one natural-language request and an optional source file:

```bash
python -m ciallo_agent.cli design "Design an E. coli YFP logic circuit." --source-file path/to/paper.pdf
```

7. If you want the planner to call OpenAI instead of the heuristic fallback:

```bash
echo "OPENAI_API_KEY=..." >> .env
echo "OPENAI_MODEL=gpt-4o-mini" >> .env
python -m ciallo_agent.cli plan "Design a 2-input AND biosensor ..."
```

The app now auto-loads `.env` from the repo root, so you do not need to export variables in every shell.

8. If Docker Desktop is running and you want to execute Cello after bundle generation:

```bash
docker pull cidarlab/cello-dnacompiler:latest
python -m ciallo_agent.cli plan "Design a 2-input AND biosensor ..." --run-cello
```

9. If you want to extend the official library with user-supplied sensors or reporters:

```bash
python -m ciallo_agent.cli author-library data/examples/custom_library_request.json
```

10. If you want the visual studio with scenario wizard, source upload, and diff view:

```bash
python -m ciallo_agent.cli serve --host 127.0.0.1 --port 8000
```

Then open the local URL printed by the server. The studio lets you switch between:

- pure natural language
- paper-assisted
- custom components
- official-library quick design

It also shows a base-vs-generated UCF diff, a JSON editor for the generated draft, and file links for the emitted artifacts.

## Verified Run

The most reliable end-to-end test we have run so far uses the official local library and does **not** modify UCF.

Prompt:

```text
Design a compact E. coli biosensor using the official library and output YFP.
```

Result:

- the request compiled into a `DesignSpec`
- the pipeline generated `Verilog`, `input.json`, and `output.json`
- the official `Eco1C1G1T1` library was sufficient
- Cello completed successfully with `returncode = 0`
- the run selected `LacI_sensor`, `TetR_sensor`, and `YFP_reporter`

Use this prompt when you want a quick sanity check that the front-end bundle generation still works without touching UCF.

## What The CLI Does

`inspect-library`

- scans `external/Cello-v2/sample-input/ucf/files/v2`
- lists available chassis, sensors, output devices, and gate families

`plan`

- converts natural language into a `DesignSpec`
- when `OPENAI_API_KEY` is present, uses a stricter OpenAI planner prompt with schema-based output parsing
- normalizes model output back against the real local Cello libraries so unsupported sensors or devices are surfaced instead of silently invented
- selects the best-matching official Cello library bundle
- generates:
  - Verilog
  - filtered `input.json`
  - filtered `output.json`
  - copied base `UCF.json`
  - `options.csv`
  - manifest and summary files
- validates generated JSON against the official Cello schemas
- prints the Docker command needed to run Cello

`author-library`

- reads a simplified JSON spec for user-provided sensors and output devices
- extends an official base library version instead of forcing the user to hand-write raw Cello JSON
- generates:
  - `<custom>.input.json`
  - `<custom>.output.json`
  - copied base `<custom>.UCF.json`
  - manifest and summary files
- validates the resulting files against the official Cello schemas

`compile-brief`

- reads a structured JSON template for logic, inputs, output, chassis, and constraints
- deterministically maps those fields into a `DesignSpec`
- infers official local sensor and reporter names when the user only provides common names like `arabinose`, `IPTG`, or `YFP`
- generates the same downstream bundle as `plan`, but without relying on LLM reasoning for the front-end request parsing

`paper-to-ucf`

- sends a paper or PDF transcription to OpenAI for structured extraction into a `PaperUCFDraft`
- captures extracted, inferred, and missing fields separately
- also writes `input_sensor_draft.json`, `output_device_draft.json`, and `ucf_fragment.json`
- attempts to convert sequence-backed sensor/output candidates into a custom library bundle
- now emits gate/model/structure/function draft entries even when a fully schema-valid custom library cannot yet be authored

`design`

- takes one natural-language request as the primary user input
- optionally reads a paper or PDF for extra biology details
- always extracts UCF-relevant knowledge from the request text itself
- merges request-derived knowledge with source-derived knowledge when a source file is present
- tries to extend the initial local Cello library when the merged knowledge contains enough sequence-backed sensor or output data
- then runs the same downstream bundle generation flow used by `plan`
- keeps request, source, and merged knowledge artifacts alongside the final design bundle so you can inspect what came from where

`serve`

- starts a local FastAPI + browser studio
- exposes the same scenario modes as the CLI
- renders a base UCF vs generated UCF diff, a JSON editor, and local artifact links

## Current Limitations

- The scaffold does not yet synthesize brand-new UCF biological parts from SynBioHub or SBOL.
- Custom library requests are collected into a `ucf_customization.todo.json` file for later completion.
- Cello execution currently assumes the official Docker image.
- A local Docker daemon must be running before `--run-cello` can work.
- `author-library` currently supports custom input sensors and output reporters, but it still copies the base official UCF for gates and placement rules.
- `paper-to-ucf` and `design` now emit richer UCF fragments, but those gate/model/function drafts are still not guaranteed to satisfy the full official UCF schema without more domain-specific normalization.
- Automatic custom library authoring still depends on sequence-backed sensor or output entries; when the source lacks sequence data, the pipeline stops at a draft artifact layer instead of a fully compiled custom library.
- The official-library path is now the primary stable path. If the selected library is not sufficient, the studio can stop early and ask for an extension instead of pretending the base UCF can handle it.

## Recommended Next Steps

1. Keep `compile-brief` as the production-safe front-end path and use `plan` as the friendly natural-language layer.
2. Add a real parts database layer from SynBioHub or your own curated lab tables.
3. Improve natural-language extraction so user-supplied proteins, promoters, and sequences map more consistently into draft sensor/output/gate candidates.
4. Tighten the draft-to-UCF normalization layer so more gate candidates can become schema-valid custom UCF extensions.
5. Add SBOL post-processing, Hill-parameter completeness checks, and Tellurium or SBML export hooks for downstream simulation.
