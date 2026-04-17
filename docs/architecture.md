# Architecture

## Core Flow

```text
Natural language request
  -> OpenAI structured planner or heuristic fallback
  -> DesignSpec
  -> Official Cello library retrieval
  -> Verilog + input/output/UCF bundle generation
  -> JSON schema validation
  -> Docker-based Cello execution
  -> Future SBOL/Tellurium analysis
```

## Components

### 1. Planner

The planner converts a free-form user request into a strongly-typed `DesignSpec`.

Outputs include:

- target chassis
- chosen or preferred sensors
- chosen output device
- logic description
- Verilog module
- manual review notes
- custom library requests

### 2. Library Index

The library index reads the official Cello v2 sample repository and exposes:

- available chassis
- available UCF bundle versions
- available input sensors
- available output devices
- available gate types

This is the retrieval layer that grounds the agent in real Cello-compatible assets.

### 3. Artifact Generator

The generator produces a run directory containing:

- `design_spec.json`
- `manifest.json`
- `summary.md`
- `<module>.v`
- `<version>.input.json`
- `<version>.output.json`
- `<version>.UCF.json`
- `options.csv`
- optional `ucf_customization.todo.json`

### 4. Validation Layer

Generated JSON is validated against the official Cello schemas from:

- `sample-input/ucf/schemas/v2/input_sensor_file.schema.json`
- `sample-input/ucf/schemas/v2/output_device_file.schema.json`
- `sample-input/ucf/schemas/v2/ucf.schema.json`

### 5. Cello Runner

The runner currently wraps the official Docker image:

- mounts the generated bundle as `/root/input`
- mounts a dedicated output directory as `/root/output`
- executes the documented `org.cellocad.v2.DNACompiler.runtime.Main` entrypoint

## Why This Split

This decomposition keeps the project easy to extend:

- swap planner prompts without changing retrieval
- add SynBioHub retrieval without changing the Cello wrapper
- add Tellurium after Cello output without changing bundle generation
- keep manual review points visible for semi-automatic workflows

