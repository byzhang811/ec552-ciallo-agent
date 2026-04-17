from ciallo_agent.ucf_diff import build_ucf_diff


def test_build_ucf_diff_reports_added_modified_and_removed_items() -> None:
    base = [
        {"collection": "header", "version": "Eco1C1G1T1", "description": "base"},
        {"collection": "logic_constraints", "available_gates": [{"type": "NOR", "max_instances": 12}]},
        {"collection": "gates", "name": "BaseGate", "gate_type": "NOR", "model": "BaseGate_model"},
    ]
    generated = [
        {"collection": "header", "version": "Eco1C1G1T1_generated", "description": "generated"},
        {
            "collection": "logic_constraints",
            "available_gates": [{"type": "NOR", "max_instances": 12}, {"type": "AND", "max_instances": True}],
        },
        {"collection": "gates", "name": "BaseGate", "gate_type": "NOR", "model": "BaseGate_model_v2"},
        {"collection": "gates", "name": "NewGate", "gate_type": "NOR", "model": "NewGate_model"},
    ]

    diff = build_ucf_diff(base, generated)

    assert diff["summary"]["added"] == 1
    assert diff["summary"]["modified"] == 3
    collections = {item["collection"] for item in diff["collections"]}
    assert "header" in collections
    assert "logic_constraints" in collections
    assert "gates" in collections
