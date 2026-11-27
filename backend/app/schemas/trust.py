from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


RuleType = Literal["NOT_NULL", "UNIQUE", "RANGE", "REGEX", "ALLOWED_VALUES", "MIN_ROW_COUNT"]


def validate_config(rule_type: str, config: dict[str, Any]) -> dict[str, Any]:
    required = {
        "NOT_NULL": set(), "UNIQUE": set(), "RANGE": set(), "REGEX": {"pattern"},
        "ALLOWED_VALUES": {"values"}, "MIN_ROW_COUNT": {"minimum"},
    }
    if rule_type not in required or not isinstance(config, dict):
        raise ValueError("Invalid rule type or config")
    allowed = {
        "NOT_NULL": set(), "UNIQUE": set(), "RANGE": {"minimum", "maximum"},
        "REGEX": {"pattern"}, "ALLOWED_VALUES": {"values"}, "MIN_ROW_COUNT": {"minimum"},
    }[rule_type]
    if not required[rule_type].issubset(config) or set(config) - allowed:
        raise ValueError("Config fields do not match rule type")
    if rule_type == "RANGE":
        if not config or any(not isinstance(v, (int, float)) or isinstance(v, bool) for v in config.values()):
            raise ValueError("RANGE requires numeric minimum and/or maximum")
        if "minimum" in config and "maximum" in config and config["minimum"] > config["maximum"]:
            raise ValueError("RANGE minimum must not exceed maximum")
    if rule_type == "REGEX":
        import re
        pattern = config["pattern"]
        if not isinstance(pattern, str) or not pattern or len(pattern) > 500:
            raise ValueError("REGEX pattern must be 1-500 characters")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError("REGEX pattern is invalid") from exc
    if rule_type == "ALLOWED_VALUES" and (not isinstance(config["values"], list) or not config["values"] or len(config["values"]) > 500):
        raise ValueError("ALLOWED_VALUES needs 1-500 values")
    if rule_type == "MIN_ROW_COUNT" and (not isinstance(config["minimum"], int) or isinstance(config["minimum"], bool) or config["minimum"] < 0):
        raise ValueError("MIN_ROW_COUNT minimum must be a non-negative integer")
    return config


class QualityRuleCreate(BaseModel):
    column_name: str | None = Field(default=None, max_length=200)
    rule_type: RuleType
    config_json: dict[str, Any] = Field(default_factory=dict)
    severity: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    enabled: bool = True

    @model_validator(mode="after")
    def validate_rule(self):
        if self.rule_type != "MIN_ROW_COUNT" and not self.column_name:
            raise ValueError("column_name is required for this rule")
        validate_config(self.rule_type, self.config_json)
        return self


class QualityRulePatch(BaseModel):
    column_name: str | None = Field(default=None, max_length=200)
    config_json: dict[str, Any] | None = None
    severity: Literal["LOW", "MEDIUM", "HIGH"] | None = None
    enabled: bool | None = None


class FreshnessPatch(BaseModel):
    freshness_target_hours: int = Field(ge=1, le=8760)


class TrustComputeResponse(BaseModel):
    id: UUID
    asset_id: UUID
    overall_score: float | None
    metrics: dict[str, Any]
    measured_metrics: list[str]
    excluded_metrics: list[str]
    rule_results: list[dict[str, Any]]
    limitations: list[str]
    sample_rows: int
    total_rows: int | None
    sampled: bool
    trigger: str
    computed_at: datetime
    last_successful_validation: str | None = None


class TrustExplainResponse(BaseModel):
    ai_estimate: Literal[True]
    summary: str
    recommendations: list[str]
