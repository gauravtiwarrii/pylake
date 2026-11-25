from app.services.pipeline_graph import PipelineGraphError, validate_pipeline_graph


def step(key: str, order: int, dependencies: list[str] | None = None, step_type: str = "SOURCE_DATASET"):
    return {
        "step_key": key,
        "name": key,
        "step_type": step_type,
        "dependencies": dependencies or [],
        "execution_order": order,
    }


def test_dependency_ordering():
    steps = [
        step("quality", 3, ["transform"], "DATA_QUALITY"),
        step("source", 1),
        step("transform", 2, ["source"], "TRANSFORM"),
    ]
    ordered = validate_pipeline_graph(steps)
    assert [item["step_key"] for item in ordered] == ["source", "transform", "quality"]


def test_missing_dependency_rejected():
    try:
        validate_pipeline_graph([step("quality", 1, ["missing"], "DATA_QUALITY")])
        raise AssertionError("Missing dependency should fail")
    except PipelineGraphError:
        pass


def test_circle_rejected():
    steps = [
        step("a", 1, ["b"]),
        step("b", 2, ["a"]),
    ]
    try:
        validate_pipeline_graph(steps)
        raise AssertionError("Cycle should fail")
    except PipelineGraphError:
        pass


def test_duplicate_step_identifier_rejected():
    try:
        validate_pipeline_graph([step("source", 1), step("source", 2)])
        raise AssertionError("Duplicate identifier should fail")
    except PipelineGraphError:
        pass
