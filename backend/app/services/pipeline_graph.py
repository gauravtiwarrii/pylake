from collections import deque

ALLOWED_STEP_TYPES = {"SOURCE_DATASET", "TRANSFORM", "DATA_QUALITY", "SQL_QUERY", "MATERIALIZE"}


class PipelineGraphError(ValueError):
    pass


def validate_pipeline_graph(steps: list[dict]) -> list[dict]:
    if len(steps) > 100:
        raise PipelineGraphError("Pipeline cannot contain more than 100 steps")

    by_key: dict[str, dict] = {}
    for step in steps:
        key = step["step_key"]
        if key in by_key:
            raise PipelineGraphError(f"Duplicate step identifier: {key}")
        if step["step_type"] not in ALLOWED_STEP_TYPES:
            raise PipelineGraphError(f"Unsupported step type: {step['step_type']}")
        by_key[key] = step

    for step in steps:
        for dependency in step.get("dependencies", []):
            if dependency not in by_key:
                raise PipelineGraphError(
                    f"Step '{step['step_key']}' references missing dependency '{dependency}'"
                )
            if dependency == step["step_key"]:
                raise PipelineGraphError(f"Step '{step['step_key']}' cannot depend on itself")

    in_degree = {key: len(step.get("dependencies", [])) for key, step in by_key.items()}
    dependents: dict[str, list[str]] = {key: [] for key in by_key}
    for step in steps:
        for dependency in step.get("dependencies", []):
            dependents[dependency].append(step["step_key"])

    ready = deque(sorted(
        (key for key, degree in in_degree.items() if degree == 0),
        key=lambda key: (by_key[key].get("execution_order", 0), key),
    ))
    ordered: list[dict] = []
    while ready:
        key = ready.popleft()
        ordered.append(by_key[key])
        for dependent in sorted(dependents[key], key=lambda item: (by_key[item].get("execution_order", 0), item)):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                ready.append(dependent)

    if len(ordered) != len(steps):
        raise PipelineGraphError("Circular pipeline dependency detected")
    return ordered
