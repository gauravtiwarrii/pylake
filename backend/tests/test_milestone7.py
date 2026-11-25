from app.core.observability import redact


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
