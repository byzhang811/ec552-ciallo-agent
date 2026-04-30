from __future__ import annotations

import argparse
from pathlib import Path
from collections import defaultdict
import json

import json5


def classify_node(node_type: str) -> str:
    if node_type == "PRIMARY_INPUT":
        return "input"
    if node_type == "PRIMARY_OUTPUT":
        return "output"
    return "gate"


def normalize_netlist(raw: dict) -> dict:
    raw_nodes = raw.get("nodes", [])
    raw_edges = raw.get("edges", [])

    node_map: dict[str, dict] = {}
    incoming: dict[str, list[str]] = defaultdict(list)
    outgoing: dict[str, list[str]] = defaultdict(list)

    # 1) 先整理节点
    for node in raw_nodes:
        name = node["name"]
        node_type = node["nodeType"]

        if name in node_map:
            raise ValueError(f"Duplicate node name found: {name}")

        node_map[name] = {
            "id": name,
            "kind": classify_node(node_type),   # input / output / gate
            "node_type": node_type,             # 原始类型，例如 NOR / NOT / PRIMARY_INPUT
            "device_name": node.get("deviceName"),
            "partition_id": node.get("partitionID"),
            "predecessors": [],
            "successors": [],
        }

    # 2) 整理边，并构建前驱后继关系
    normalized_edges = []
    for edge in raw_edges:
        src = edge["src"]
        dst = edge["dst"]

        if src not in node_map:
            raise ValueError(f"Edge source node not found: {src}")
        if dst not in node_map:
            raise ValueError(f"Edge destination node not found: {dst}")

        outgoing[src].append(dst)
        incoming[dst].append(src)

        normalized_edges.append({
            "id": edge["name"],
            "src": src,
            "dst": dst,
        })

    # 3) 回填 predecessors / successors
    for node_name, info in node_map.items():
        info["predecessors"] = incoming[node_name]
        info["successors"] = outgoing[node_name]

    # 4) 生成分类列表
    inputs = [name for name, info in node_map.items() if info["kind"] == "input"]
    outputs = [name for name, info in node_map.items() if info["kind"] == "output"]
    gates = [name for name, info in node_map.items() if info["kind"] == "gate"]

    # 5) 可选：做一些简单检查
    for name in inputs:
        if node_map[name]["predecessors"]:
            raise ValueError(f"Input node {name} should not have predecessors")

    for name in outputs:
        if node_map[name]["successors"]:
            raise ValueError(f"Output node {name} should not have successors")

    normalized = {
        "circuit_name": raw.get("name"),
        "source_file": raw.get("inputFilename"),
        "nodes": node_map,
        "edges": normalized_edges,
        "inputs": inputs,
        "outputs": outputs,
        "gates": gates,
    }

    return normalized


def load_netlist(path: Path) -> dict:
    text = path.read_text(encoding="utf-8").strip()
    # 处理“整个文件只有一个对象，但对象后面多了一个逗号”的情况
    if text.endswith("},"):
        text = text[:-1]

    return json5.loads(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize a Cello-style netlist")
    parser.add_argument("input", type=Path, help="Path to raw netlist file")
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Path to save normalized netlist as JSON"
    )
    args = parser.parse_args()

    raw = load_netlist(args.input)
    normalized = normalize_netlist(raw)

    text = json.dumps(normalized, indent=2, ensure_ascii=False)

    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()