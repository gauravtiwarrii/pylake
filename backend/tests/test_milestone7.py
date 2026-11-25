from app.core.observability import redact
from app.engines.query_validator import SQLValidationError, validate_read_only_sql
from app.services.pipeline_graph import PipelineGraphError, validate_pipeline_graph


def test_structured_logging_redacts_sensitive_values():
    value = {
        "password": "secret",
        "Authorization": "Bearer private-token",
        "api_key": "12345",
        "safe": "visible",
    }
    redacted = redact(value)
    assert redacted["password"] == "[REDACTED]"
    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["safe"] == "visible"


def test_redactor_masks_bearer_text():
    assert redact("Authorization: Bearer abc123") == "Authorization: Bearer [REDACTED]"


def test_milestone7_read_only_validator_blocks_external_access():
    blocked = [
        "SELECT * FROM read_text('/etc/passwd')",
        "SELECT * FROM postgres_scan('host=localhost')",
        "ATTACH 'database.db' AS external",
        "SELECT * FROM customers; SELECT * FROM orders",
    ]
    for sql in blocked:
        try:
            validate_read_only_sql(sql)
            raise AssertionError(f"Expected rejection: {sql}")
        except SQLValidationError:
            pass


def test_milestone7_graph_validation_still_detects_cycles():
    steps = [
        {"step_key": "a", "name": "A", "step_type": "SOURCE_DATASET", "dependencies": ["b"], "execution_order": 1},
        {"step_key": "b", "name": "B", "step_type": "TRANSFORM", "dependencies": ["a"], "execution_order": 2},
    ]
    try:
        validate_pipeline_graph(steps)
        raise AssertionError("Cycle should be rejected")
    except PipelineGraphError:
        pass
