from __future__ import annotations

import argparse
import json
from pathlib import Path
from collections import defaultdict, deque
from typing import Any


# ---------- tolerant JSON/JSON5 loader ----------

def load_jsonish(path: Path) -> Any:
    text = path.read_text(encoding="utf-8").rstrip()

    # tolerate one trailing comma at end of file
    if text.endswith(","):
        text = text[:-1].rstrip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    try:
        import json5  # type: ignore
        return json5.loads(text)
    except Exception as e:
        raise ValueError(f"Failed to parse {path}: {e}")


# ---------- helpers ----------

def sanitize_name(name: str) -> str:
    out = []
    for ch in name:
        if ch.isalnum() or ch == "_":
            out.append(ch)
        else:
            out.append("_")
    s = "".join(out)
    while "__" in s:
        s = s.replace("__", "_")
    if not s:
        s = "node"
    if s[0].isdigit():
        s = "N_" + s
    if name.startswith("$"):
        s = "N_" + s.lstrip("_")
    return s


def list_to_param_dict(params: list[dict]) -> dict[str, Any]:
    result = {}
    for p in params:
        result[p["name"]] = p.get("value")
    return result


def build_collection_index(records: list[dict]) -> dict[str, dict[str, dict]]:
    idx: dict[str, dict[str, dict]] = defaultdict(dict)
    for rec in records:
        collection = rec.get("collection")
        name = rec.get("name")
        if collection is None or name is None:
            continue
        idx[collection][name] = rec
    return idx


def topo_sort(nodes: dict[str, dict], edges: list[dict]) -> list[str]:
    indeg = {name: 0 for name in nodes.keys()}
    graph = defaultdict(list)

    for e in edges:
        src = e["src"]
        dst = e["dst"]
        graph[src].append(dst)
        indeg[dst] += 1

    q = deque(sorted([n for n, d in indeg.items() if d == 0]))
    order = []

    while q:
        cur = q.popleft()
        order.append(cur)
        for nxt in graph[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)

    if len(order) != len(nodes):
        raise ValueError("Cycle detected in netlist; topological sort failed")

    return order


# ---------- resolvers ----------

def resolve_input_sensor(device_name: str, input_index: dict[str, dict[str, dict]]) -> dict | None:
    sensor_entry = input_index.get("input_sensors", {}).get(device_name)
    if not sensor_entry:
        return None

    model_name = sensor_entry.get("model")
    structure_name = sensor_entry.get("structure")

    model = input_index.get("models", {}).get(model_name, {})
    structure = input_index.get("structures", {}).get(structure_name, {})
    response_func_name = model.get("functions", {}).get("response_function")
    response_func = input_index.get("functions", {}).get(response_func_name, {})
    params = list_to_param_dict(model.get("parameters", []))

    return {
        "kind": "input_sensor",
        "model_ref": {
            "source": "input_lib",
            "collection": "input_sensors",
            "name": device_name,
            "model": model_name,
            "structure": structure_name,
        },
        "response": {
            "type": "sensor_linear",
            "function_name": response_func_name,
            "equation": response_func.get("equation"),
            "parameters": {
                "ymin": params.get("ymin"),
                "ymax": params.get("ymax"),
            },
        },
        "structure": {
            "outputs": structure.get("outputs", []),
        },
    }


def resolve_output_device(device_name: str, output_index: dict[str, dict[str, dict]]) -> dict | None:
    output_entry = output_index.get("output_devices", {}).get(device_name)
    if not output_entry:
        return None

    model_name = output_entry.get("model")
    structure_name = output_entry.get("structure")

    model = output_index.get("models", {}).get(model_name, {})
    structure = output_index.get("structures", {}).get(structure_name, {})
    response_func_name = model.get("functions", {}).get("response_function")
    response_func = output_index.get("functions", {}).get(response_func_name, {})
    params = list_to_param_dict(model.get("parameters", []))

    return {
        "kind": "reporter",
        "model_ref": {
            "source": "output_lib",
            "collection": "output_devices",
            "name": device_name,
            "model": model_name,
            "structure": structure_name,
        },
        "response": {
            "type": "linear_reporter",
            "function_name": response_func_name,
            "equation": response_func.get("equation"),
            "parameters": {
                "unit_conversion": params.get("unit_conversion"),
            },
        },
        "structure": {
            "inputs": structure.get("inputs", []),
            "devices": structure.get("devices", []),
        },
    }


def resolve_gate_device(device_name: str, gate_index: dict[str, dict[str, dict]]) -> dict | None:
    gate_entry = gate_index.get("gates", {}).get(device_name)
    if not gate_entry:
        return None

    model_name = gate_entry.get("model")
    structure_name = gate_entry.get("structure")

    model = gate_index.get("models", {}).get(model_name, {})
    structure = gate_index.get("structures", {}).get(structure_name, {})

    response_func_name = model.get("functions", {}).get("response_function")
    input_comp_name = model.get("functions", {}).get("input_composition")

    response_func = gate_index.get("functions", {}).get(response_func_name, {})
    input_comp_func = gate_index.get("functions", {}).get(input_comp_name, {})
    params = list_to_param_dict(model.get("parameters", []))

    return {
        "kind": "gate",
        "model_ref": {
            "source": "gate_lib",
            "collection": "gates",
            "name": device_name,
            "model": model_name,
            "structure": structure_name,
        },
        "gate_meta": {
            "gate_type": gate_entry.get("gate_type"),
            "system": gate_entry.get("system"),
            "group": gate_entry.get("group"),
            "regulator": gate_entry.get("regulator"),
            "color": gate_entry.get("color"),
        },
        "response": {
            "type": "hill_repression",
            "function_name": response_func_name,
            "equation": response_func.get("equation"),
            "input_composition_name": input_comp_name,
            "input_composition_equation": input_comp_func.get("equation"),
            "parameters": {
                "ymin": params.get("ymin"),
                "ymax": params.get("ymax"),
                "K": params.get("K"),
                "n": params.get("n"),
            },
        },
        "structure": {
            "inputs": structure.get("inputs", []),
            "outputs": structure.get("outputs", []),
            "devices": structure.get("devices", []),
        },
    }


# ---------- main builder ----------

def build_sim_ir(
    normalized_netlist: dict,
    input_lib: list[dict],
    output_lib: list[dict],
    gate_lib: list[dict],
) -> dict:
    input_index = build_collection_index(input_lib)
    output_index = build_collection_index(output_lib)
    gate_index = build_collection_index(gate_lib)

    raw_nodes = normalized_netlist["nodes"]
    raw_edges = normalized_netlist["edges"]

    if isinstance(raw_nodes, dict):
        nodes_map = raw_nodes
    else:
        nodes_map = {n["id"]: n for n in raw_nodes}

    sim_nodes: dict[str, dict] = {}
    warnings: list[str] = []

    for node_name, node in nodes_map.items():
        base = {
            "id": node_name,
            "kind": node["kind"],
            "node_type": node["node_type"],
            "device_name": node.get("device_name"),
            "partition_id": node.get("partition_id"),
            "predecessors": node.get("predecessors", []),
            "successors": node.get("successors", []),
            "signal": {},
            "model_ref": None,
            "response": None,
            "structure": None,
            "resolved": False,
        }

        safe = sanitize_name(node_name)

        if node["kind"] == "input":
            base["signal"] = {
                "state_var": f"{safe}_STATE",
                "output_var": f"{safe}_OUT",
            }
            resolved = resolve_input_sensor(node.get("device_name"), input_index)
            if resolved is None:
                warnings.append(f"Input sensor not found in input library: {node.get('device_name')}")
            else:
                base.update(resolved)
                base["resolved"] = True

        elif node["kind"] == "output":
            src_var = None
            if base["predecessors"]:
                pred_safe = sanitize_name(base["predecessors"][0])
                src_var = f"{pred_safe}_OUT"

            base["signal"] = {
                "input_var": src_var,
                "output_var": f"{safe}_OUT",
            }
            resolved = resolve_output_device(node.get("device_name"), output_index)
            if resolved is None:
                warnings.append(f"Output device not found in output library: {node.get('device_name')}")
            else:
                base.update(resolved)
                base["resolved"] = True

        else:
            base["signal"] = {
                "state_var": f"{safe}_X",
                "output_var": f"{safe}_OUT",
            }
            resolved = resolve_gate_device(node.get("device_name"), gate_index)
            if resolved is None:
                warnings.append(f"Gate not found in UCF gate library: {node.get('device_name')}")
                base["response"] = {
                    "type": "UNRESOLVED_GATE",
                    "parameters": None,
                }
            else:
                base.update(resolved)
                base["resolved"] = True

        sim_nodes[node_name] = base

    order = topo_sort(nodes_map, raw_edges)

    input_signals = {}
    for name, n in sim_nodes.items():
        if n["kind"] == "input_sensor":
            input_signals[name] = {
                "type": "step",
                "t_start": 20.0,
                "from": 0.0,
                "to": 1.0,
            }

    default_kdeg = 1.0
    kdeg_overrides = {}
    for name, n in sim_nodes.items():
        if n["kind"] == "gate":
            kdeg_overrides[name] = default_kdeg

    sim_ir = {
        "circuit_name": normalized_netlist.get("circuit_name"),
        "source_file": normalized_netlist.get("source_file"),
        "simulation": {
            "time": {
                "start": 0.0,
                "end": 100.0,
                "points": 1000,
            },
            "default_kdeg": default_kdeg,
            "kdeg_overrides": kdeg_overrides,
            "input_signals": input_signals,
        },
        "nodes": sim_nodes,
        "edges": raw_edges,
        "topology": {
            "inputs": normalized_netlist.get("inputs", []),
            "outputs": normalized_netlist.get("outputs", []),
            "gates": normalized_netlist.get("gates", []),
            "topological_order": order,
        },
        "warnings": warnings,
    }

    return sim_ir


# ---------- CLI ----------

def main() -> None:
    parser = argparse.ArgumentParser(description="Build simulation IR from normalized netlist and libraries")
    parser.add_argument("normalized_netlist", type=Path, help="Path to normalized netlist JSON/JSON5")
    parser.add_argument("--input-lib", required=True, type=Path, help="Path to input sensor library JSON")
    parser.add_argument("--output-lib", required=True, type=Path, help="Path to output device library JSON")
    parser.add_argument("--gate-lib", required=True, type=Path, help="Path to UCF gate library JSON")
    parser.add_argument("-o", "--output", required=True, type=Path, help="Output simulation IR JSON file")
    args = parser.parse_args()

    normalized_netlist = load_jsonish(args.normalized_netlist)
    input_lib = load_jsonish(args.input_lib)
    output_lib = load_jsonish(args.output_lib)
    gate_lib = load_jsonish(args.gate_lib)

    if not isinstance(input_lib, list):
        raise ValueError("Input library file must contain a top-level array")
    if not isinstance(output_lib, list):
        raise ValueError("Output library file must contain a top-level array")
    if not isinstance(gate_lib, list):
        raise ValueError("Gate library file must contain a top-level array")

    sim_ir = build_sim_ir(normalized_netlist, input_lib, output_lib, gate_lib)

    args.output.write_text(
        json.dumps(sim_ir, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Simulation IR written to: {args.output}")
    if sim_ir["warnings"]:
        print("Warnings:")
        for w in sim_ir["warnings"]:
            print(f"  - {w}")


if __name__ == "__main__":
    main()