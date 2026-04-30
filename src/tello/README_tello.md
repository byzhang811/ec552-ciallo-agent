# Tello Scripts

## Requirement  
Tellurium, json5 are needed.

This folder contains three scripts:

## `tello_netlist.py`
Reads the raw netlist file and extracts the circuit topology.

Main purpose:
- read `nodes` and `edges`
- normalize the netlist structure
- classify inputs, outputs, and gates

Example:
```bash
python tello_netlist.py raw_netlist.json -o normalized_netlist.json
```

## `tello_build.py`
Reads the normalized netlist and library files, then builds a simulation intermediate file.

Main purpose:
- attach input sensor parameters
- attach gate Hill-function parameters
- attach output reporter parameters
- generate a simulation-ready intermediate file

Example:
```bash
python tello_build.py normalized_netlist.json \
  --input-lib Eco1C1G1T1.input.json \
  --output-lib Eco1C1G1T1.output.json \
  --gate-lib Eco1C1G1T1.UCF.json \
  -o simulation_ir.json
```

## `tello_simulation.py`
Reads the simulation intermediate file, generates an Antimony model, and runs Tellurium simulation.

Main purpose:
- generate `.ant` model text
- run simulation
- export `.csv` results
- export `.png` plot

Example:
```bash
python tello_simulation.py simulation_ir.json --show-ant
```

## Recommended Workflow

```bash
python tello_netlist.py raw_netlist.json -o normalized_netlist.json

python tello_build.py normalized_netlist.json \
  --input-lib Eco1C1G1T1.input.json \
  --output-lib Eco1C1G1T1.output.json \
  --gate-lib Eco1C1G1T1.UCF.json \
  -o simulation_ir.json

python tello_simulation.py simulation_ir.json --show-ant
```
