from dataclasses import asdict, dataclass


ROLE_RANK = {"VIEWER": 0, "EDITOR": 1, "ADMIN": 2, "OWNER": 3}


@dataclass(frozen=True)
class AIToolDefinition:
    name: str
    description: str
    minimum_role: str
    application_role: str | None
    page_types: tuple[str, ...]
    read_only: bool
    approval_required: bool


AI_TOOL_REGISTRY = {
    tool.name: tool
    for tool in (
        AIToolDefinition("profile_dataset", "Compute bounded dataset profile metrics.", "VIEWER", None, ("data", "dataset"), True, False),
        AIToolDefinition("analyze_data_quality", "Inspect verified lakehouse quality metrics.", "VIEWER", None, ("lakehouse", "quality"), True, False),
        AIToolDefinition("explain_schema", "Explain selected dataset or table schema.", "VIEWER", None, ("data", "dataset", "lakehouse", "catalog"), True, False),
        AIToolDefinition("suggest_cleaning_transformations", "Draft a supported data-cleaning transformation.", "VIEWER", "EDITOR", ("data", "dataset", "lakehouse", "quality"), True, True),
        AIToolDefinition("generate_sql", "Generate and validate a read-only workspace SQL draft.", "VIEWER", None, ("sql",), True, False),
        AIToolDefinition("explain_sql", "Explain the current SQL without executing it.", "VIEWER", None, ("sql",), True, False),
        AIToolDefinition("debug_sql", "Diagnose SQL from the supplied query and error.", "VIEWER", None, ("sql",), True, False),
        AIToolDefinition("recommend_lakehouse_improvements", "Explain lakehouse options using verified table metadata.", "VIEWER", "EDITOR", ("lakehouse",), True, True),
        AIToolDefinition("generate_pipeline_draft", "Generate a validated pipeline draft without saving or running it.", "VIEWER", "EDITOR", ("pipelines",), True, True),
        AIToolDefinition("diagnose_pipeline_failure", "Explain an observed pipeline failure.", "VIEWER", None, ("dashboard", "pipelines"), True, False),
        AIToolDefinition("explain_lineage", "Explain observed lineage relationships.", "VIEWER", None, ("catalog", "lineage", "lakehouse"), True, False),
        AIToolDefinition("summarize_workspace_activity", "Summarize bounded, authorized audit activity.", "VIEWER", None, ("audit", "dashboard", "workspace"), True, False),
        AIToolDefinition("draft_catalog_metadata", "Draft catalog description or tag changes for review.", "VIEWER", "EDITOR", ("catalog",), True, True),
    )
}


def has_tool_permission(role: str, tool: AIToolDefinition) -> bool:
    return ROLE_RANK.get(role, -1) >= ROLE_RANK[tool.minimum_role]


def available_tools(role: str, page_type: str | None = None) -> list[dict[str, object]]:
    return [
        {
            **asdict(tool),
            "page_types": list(tool.page_types),
        }
        for tool in AI_TOOL_REGISTRY.values()
        if has_tool_permission(role, tool)
        and (page_type is None or page_type in tool.page_types)
    ]
