from __future__ import annotations

import json
from collections import Counter, defaultdict
from copy import deepcopy
from typing import Any


def _fingerprint(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _diff_scalar(before: Any, after: Any, path: str) -> list[dict[str, Any]]:
    if before == after:
        return []
    return [
        {
            "path": path or "$",
            "before": before,
            "after": after,
            "kind": "updated",
        }
    ]


def _diff_list(before: list[Any], after: list[Any], path: str) -> list[dict[str, Any]]:
    if before == after:
        return []

    diffs: list[dict[str, Any]] = []
    shared = min(len(before), len(after))
    for index in range(shared):
        diffs.extend(_diff_any(before[index], after[index], f"{path}[{index}]"))
    for index in range(shared, len(before)):
        diffs.append(
            {
                "path": f"{path}[{index}]",
                "before": before[index],
                "after": None,
                "kind": "removed",
            }
        )
    for index in range(shared, len(after)):
        diffs.append(
            {
                "path": f"{path}[{index}]",
                "before": None,
                "after": after[index],
                "kind": "added",
            }
        )
    return diffs


def _diff_dict(before: dict[str, Any], after: dict[str, Any], path: str) -> list[dict[str, Any]]:
    if before == after:
        return []

    diffs: list[dict[str, Any]] = []
    keys = sorted(set(before) | set(after))
    for key in keys:
        child_path = f"{path}.{key}" if path else key
        if key not in before:
            diffs.append(
                {
                    "path": child_path,
                    "before": None,
                    "after": after[key],
                    "kind": "added",
                }
            )
            continue
        if key not in after:
            diffs.append(
                {
                    "path": child_path,
                    "before": before[key],
                    "after": None,
                    "kind": "removed",
                }
            )
            continue
        diffs.extend(_diff_any(before[key], after[key], child_path))
    return diffs


def _diff_any(before: Any, after: Any, path: str) -> list[dict[str, Any]]:
    if isinstance(before, dict) and isinstance(after, dict):
        return _diff_dict(before, after, path)
    if isinstance(before, list) and isinstance(after, list):
        return _diff_list(before, after, path)
    return _diff_scalar(before, after, path)


def _group_by_collection(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        if isinstance(item, dict):
            grouped[item.get("collection", "__unknown__")].append(item)
    return grouped


def _named_items(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    named: dict[str, dict[str, Any]] = {}
    for item in items:
        name = item.get("name")
        if name:
            named[str(name)] = item
    return named


def _unnamed_fingerprints(items: list[dict[str, Any]]) -> Counter[str]:
    fingerprints: Counter[str] = Counter()
    for item in items:
        if not item.get("name"):
            fingerprints[_fingerprint(item)] += 1
    return fingerprints


def _collection_change(
    collection: str,
    before_items: list[dict[str, Any]],
    after_items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if collection in {"header", "logic_constraints"} and len(before_items) == 1 and len(after_items) == 1:
        changes = _diff_any(before_items[0], after_items[0], collection)
        if not changes:
            return None
        return {
            "collection": collection,
            "base_count": len(before_items),
            "generated_count": len(after_items),
            "added": 0,
            "removed": 0,
            "modified": 1,
            "items": [
                {
                    "collection": collection,
                    "key": collection,
                    "change_type": "modified",
                    "before": before_items[0],
                    "after": after_items[0],
                    "changes": changes,
                }
            ],
        }

    before_named = _named_items(before_items)
    after_named = _named_items(after_items)
    before_unnamed = [item for item in before_items if not item.get("name")]
    after_unnamed = [item for item in after_items if not item.get("name")]

    item_changes: list[dict[str, Any]] = []

    for name in sorted(set(before_named) | set(after_named)):
        before_item = before_named.get(name)
        after_item = after_named.get(name)
        if before_item is None:
            item_changes.append(
                {
                    "collection": collection,
                    "key": name,
                    "change_type": "added",
                    "before": None,
                    "after": after_item,
                    "changes": [],
                }
            )
            continue
        if after_item is None:
            item_changes.append(
                {
                    "collection": collection,
                    "key": name,
                    "change_type": "removed",
                    "before": before_item,
                    "after": None,
                    "changes": [],
                }
            )
            continue
        changes = _diff_any(before_item, after_item, collection)
        if changes:
            item_changes.append(
                {
                    "collection": collection,
                    "key": name,
                    "change_type": "modified",
                    "before": before_item,
                    "after": after_item,
                    "changes": changes,
                }
            )

    before_fps = _unnamed_fingerprints(before_items)
    after_fps = _unnamed_fingerprints(after_items)
    for fingerprint in sorted(set(before_fps) | set(after_fps)):
        before_count = before_fps.get(fingerprint, 0)
        after_count = after_fps.get(fingerprint, 0)
        if before_count == after_count:
            continue
        payload = json.loads(fingerprint)
        if before_count > after_count:
            for _ in range(before_count - after_count):
                item_changes.append(
                    {
                        "collection": collection,
                        "key": f"{collection}[]",
                        "change_type": "removed",
                        "before": payload,
                        "after": None,
                        "changes": [],
                    }
                )
        else:
            for _ in range(after_count - before_count):
                item_changes.append(
                    {
                        "collection": collection,
                        "key": f"{collection}[]",
                        "change_type": "added",
                        "before": None,
                        "after": payload,
                        "changes": [],
                    }
                )

    if not item_changes:
        return None

    added = sum(1 for item in item_changes if item["change_type"] == "added")
    removed = sum(1 for item in item_changes if item["change_type"] == "removed")
    modified = sum(1 for item in item_changes if item["change_type"] == "modified")
    return {
        "collection": collection,
        "base_count": len(before_items),
        "generated_count": len(after_items),
        "added": added,
        "removed": removed,
        "modified": modified,
        "items": item_changes,
    }


def build_ucf_diff(
    base_items: list[dict[str, Any]],
    generated_items: list[dict[str, Any]],
) -> dict[str, Any]:
    base_grouped = _group_by_collection(base_items)
    generated_grouped = _group_by_collection(generated_items)
    all_collections = sorted(set(base_grouped) | set(generated_grouped))

    collections: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    added = removed = modified = 0

    for collection in all_collections:
        collection_change = _collection_change(
            collection,
            deepcopy(base_grouped.get(collection, [])),
            deepcopy(generated_grouped.get(collection, [])),
        )
        if collection_change is None:
            continue
        collections.append(collection_change)
        for item in collection_change["items"]:
            changes.append(item)
        added += collection_change["added"]
        removed += collection_change["removed"]
        modified += collection_change["modified"]

    return {
        "summary": {
            "base_item_count": len(base_items),
            "generated_item_count": len(generated_items),
            "collection_count": len(all_collections),
            "added": added,
            "removed": removed,
            "modified": modified,
        },
        "collections": collections,
        "changes": changes,
    }


def format_ucf_diff_summary(diff: dict[str, Any]) -> str:
    summary = diff.get("summary", {})
    return (
        f"base={summary.get('base_item_count', 0)} | "
        f"generated={summary.get('generated_item_count', 0)} | "
        f"added={summary.get('added', 0)} | removed={summary.get('removed', 0)} | "
        f"modified={summary.get('modified', 0)}"
    )
