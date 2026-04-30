from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import tellurium as te


# ---------- IO ----------

def load_jsonish(path: Path) -> Any:
    text = path.read_text(encoding="utf-8").rstrip()
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

def safe_replace(expr: str, mapping: dict[str, str]) -> str:
    """
    用正则按变量边界替换，避免把别的名字中间误替掉。
    """
    out = expr
    # 长名字优先
    for key in sorted(mapping.keys(), key=len, reverse=True):
        pattern = rf'(?<![A-Za-z0-9_]){re.escape(key)}(?![A-Za-z0-9_])'
        out = re.sub(pattern, mapping[key], out)
    return out


def unique_keep_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def get_plot_selections(ir: dict) -> list[str]:
    sels = ["time"]

    # 输入：画用户定义的原始输入状态（step 信号）
    for node_name in ir["topology"]["inputs"]:
        node = ir["nodes"][node_name]
        if node["kind"] == "input_sensor":
            sels.append(node["signal"]["state_var"])
            # 如果你更想画 sensor 输出而不是原始 step，
            # 就把上面这一行改成：
            # sels.append(node["signal"]["output_var"])

    # 输出：画最终输出
    for node_name in ir["topology"]["outputs"]:
        node = ir["nodes"][node_name]
        sels.append(node["signal"]["output_var"])

    return unique_keep_order(sels)

# ---------- expression builders ----------

def build_input_sensor_lines(node_name: str, node: dict, input_signal: dict) -> list[str]:
    signal = node["signal"]
    state_var = signal["state_var"]
    out_var = signal["output_var"]

    response = node["response"]
    eq = response["equation"]
    ymin = response["parameters"]["ymin"]
    ymax = response["parameters"]["ymax"]

    if ymin is None or ymax is None:
        raise ValueError(f"Input sensor {node_name} missing ymin/ymax")

    if input_signal["type"] != "step":
        raise ValueError(f"Only step input is supported now, got {input_signal['type']} for {node_name}")

    t_start = float(input_signal["t_start"])
    from_val = float(input_signal["from"])
    to_val = float(input_signal["to"])

    if not (0.0 <= from_val <= 1.0 and 0.0 <= to_val <= 1.0):
        raise ValueError(f"Input {node_name} step values must be in [0,1]")

    eq2 = eq.replace("$STATE", state_var)
    eq2 = safe_replace(eq2, {
        "ymin": str(ymin),
        "ymax": str(ymax),
    })

    event_name = f"E_{state_var}"

    lines = [
        f"  {state_var} = {from_val}",
        f"  {event_name}: at time > {t_start}: {state_var} = {to_val}",
        f"  {out_var} := {eq2}",
    ]
    return lines


def build_gate_input_composition(node_name: str, node: dict, nodes: dict[str, dict]) -> str:
    preds = node["predecessors"]
    if not preds:
        raise ValueError(f"Gate {node_name} has no predecessors")

    pred_out_vars = [nodes[p]["signal"]["output_var"] for p in preds]

    response = node["response"]
    comp_eq = response.get("input_composition_equation")

    # 没有组合公式时：
    if not comp_eq:
        if len(pred_out_vars) == 1:
            return pred_out_vars[0]
        return " + ".join(pred_out_vars)

    # 有组合公式时，把缺失输入补成 0
    mapping = {
        "x1": "0",
        "x2": "0",
        "x3": "0",
        "x4": "0",
    }

    for i, var in enumerate(pred_out_vars, start=1):
        mapping[f"x{i}"] = f"({var})"

    return safe_replace(comp_eq, mapping)


def build_gate_target_expr(node_name: str, node: dict, nodes: dict[str, dict]) -> str:
    response = node["response"]
    eq = response["equation"]
    params = response["parameters"]

    if eq is None or params is None:
        raise ValueError(f"Gate {node_name} missing response equation or parameters")

    input_expr = build_gate_input_composition(node_name, node, nodes)

    mapping = {
        "x": f"({input_expr})",
        "ymin": str(params["ymin"]),
        "ymax": str(params["ymax"]),
        "K": str(params["K"]),
        "n": str(params["n"]),
    }

    return safe_replace(eq, mapping)


def build_gate_lines(node_name: str, node: dict, nodes: dict[str, dict], kdeg: float) -> list[str]:
    signal = node["signal"]
    x_var = signal["state_var"]
    out_var = signal["output_var"]

    target_expr = build_gate_target_expr(node_name, node, nodes)

    kdeg_name = f"{x_var}_kdeg"
    target_var = f"{x_var}_target"

    lines = [
        f"  {x_var} = 0",
        f"  {kdeg_name} = {float(kdeg)}",
        f"  {target_var} := {target_expr}",
        f"  -> {x_var}; {kdeg_name} * ({target_var})",
        f"  {x_var} -> ; {kdeg_name} * {x_var}",
        f"  {out_var} := {x_var}",
    ]
    return lines


def build_reporter_lines(node_name: str, node: dict, nodes: dict[str, dict]) -> list[str]:
    signal = node["signal"]
    out_var = signal["output_var"]

    preds = node["predecessors"]
    if not preds:
        raise ValueError(f"Reporter {node_name} has no predecessors")

    pred_out_vars = [nodes[p]["signal"]["output_var"] for p in preds]

    if len(pred_out_vars) == 1:
        x_expr = pred_out_vars[0]
    else:
        # 当前 output IR 没把 input_composition_equation 带进来，这里先默认求和
        x_expr = " + ".join(pred_out_vars)

    response = node["response"]
    eq = response["equation"]
    c = response["parameters"]["unit_conversion"]

    eq2 = safe_replace(eq, {
        "x": f"({x_expr})",
        "c": str(c),
    })

    lines = [
        f"  {out_var} := {eq2}",
    ]
    return lines


# ---------- antimony builder ----------

def build_antimony(ir: dict) -> tuple[str, list[str]]:
    nodes = ir["nodes"]
    order = ir["topology"]["topological_order"]

    sim_cfg = ir["simulation"]
    input_signals = sim_cfg["input_signals"]
    default_kdeg = float(sim_cfg["default_kdeg"])
    kdeg_overrides = sim_cfg.get("kdeg_overrides", {})

    lines: list[str] = []
    selections: list[str] = ["time"]

    lines.append(f"model {ir['circuit_name']}()")

    for node_name in order:
        node = nodes[node_name]
        lines.append(f"  // node: {node_name} ({node['device_name']})")

        if node["kind"] == "input_sensor":
            lines.extend(build_input_sensor_lines(node_name, node, input_signals[node_name]))
            selections.append(node["signal"]["state_var"])
            selections.append(node["signal"]["output_var"])

        elif node["kind"] == "gate":
            kdeg = float(kdeg_overrides.get(node_name, default_kdeg))
            lines.extend(build_gate_lines(node_name, node, nodes, kdeg))
            selections.append(node["signal"]["state_var"])
            selections.append(node["signal"]["output_var"])

        elif node["kind"] == "reporter":
            lines.extend(build_reporter_lines(node_name, node, nodes))
            selections.append(node["signal"]["output_var"])

        else:
            raise ValueError(f"Unknown node kind: {node['kind']}")

        lines.append("")

    lines.append("end")

    antimony = "\n".join(lines)
    selections = unique_keep_order(selections)
    return antimony, selections


# ---------- simulation / export ----------

def write_csv(result, selections: list[str], out_csv: Path) -> None:
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(selections)
        for row in result:
            writer.writerow(row)


def save_plot(result, selections: list[str], plot_selections: list[str], out_png: Path) -> None:
    name_to_idx = {name: i for i, name in enumerate(selections)}

    time_idx = name_to_idx["time"]
    t = result[:, time_idx]

    plt.figure(figsize=(10, 6))

    for name in plot_selections:
        if name == "time":
            continue
        if name not in name_to_idx:
            continue
        i = name_to_idx[name]
        plt.plot(t, result[:, i], label=name)

    plt.xlabel("time")
    plt.ylabel("value")
    plt.title("Input / Output simulation")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_png, dpi=150)
    plt.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Antimony from simulation_ir and run Tellurium")
    parser.add_argument("simulation_ir", type=Path, help="Path to simulation_ir.json")
    parser.add_argument("--ant-out", type=Path, default=None, help="Output .ant file path")
    parser.add_argument("--csv-out", type=Path, default=None, help="Output .csv file path")
    parser.add_argument("--png-out", type=Path, default=None, help="Output .png plot path")
    parser.add_argument("--show-ant", action="store_true", help="Print antimony text to console")
    args = parser.parse_args()

    ir = load_jsonish(args.simulation_ir)

    antimony, selections = build_antimony(ir)

    sim_path = args.simulation_ir
    base = sim_path.with_suffix("")

    ant_out = args.ant_out or Path(str(base) + ".ant")
    csv_out = args.csv_out or Path(str(base) + ".csv")
    png_out = args.png_out or Path(str(base) + ".png")

    ant_out.write_text(antimony, encoding="utf-8")

    if args.show_ant:
        print(antimony)
        print()

    r = te.loada(antimony)

    t0 = float(ir["simulation"]["time"]["start"])
    t1 = float(ir["simulation"]["time"]["end"])
    npts = int(ir["simulation"]["time"]["points"])

    result = r.simulate(t0, t1, npts, selections=selections)

    write_csv(result, selections, csv_out)

    plot_selections = get_plot_selections(ir)
    save_plot(result, selections, plot_selections, png_out)

    print(f"Antimony written to: {ant_out}")
    print(f"CSV written to:      {csv_out}")
    print(f"Plot written to:     {png_out}")


if __name__ == "__main__":
    main()