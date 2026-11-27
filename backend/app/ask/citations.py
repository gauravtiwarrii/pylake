from typing import Any


def citation(kind: str, identifier: Any, name: str, column: str | None = None) -> dict[str, str]:
    item = {"type": kind, "id": str(identifier), "name": str(name)[:200]}
    if column:
        item["column"] = str(column)[:200]
    return item


def unique_citations(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str | None]] = set()
    result = []
    for item in items:
        key = (item["type"], item["id"], item.get("column"))
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result
