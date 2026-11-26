from typing import Any

from app.ai.tools import AI_TOOL_REGISTRY, has_tool_permission


def build_recommendations(
    context: dict[str, Any],
    page_type: str,
    role: str,
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []

    def add(
        tool_name: str,
        title: str,
        description: str,
        category: str,
        evidence: list[dict[str, str]],
        confidence: str,
        impact: str,
        risk: str = "LOW",
        arguments: dict[str, Any] | None = None,
    ) -> None:
        tool = AI_TOOL_REGISTRY[tool_name]
        if not has_tool_permission(role, tool):
            return
        recommendations.append({
            "title": title,
            "description": description,
            "category": category,
            "evidence": evidence,
            "confidence": confidence,
            "expected_impact": impact,
            "proposed_action": {"tool": tool_name, "arguments": arguments or {}},
            "risk_level": risk,
            "required_permissions": [tool.application_role or tool.minimum_role],
            "approval_required": tool.approval_required,
        })

    datasets = context.get("datasets", [])
    if page_type == "dataset" and datasets:
        dataset = datasets[0]
        dataset_id = dataset.get("id")
        if dataset.get("status") == "COMPLETED" and dataset_id:
            add(
                "profile_dataset",
                f"Profile {dataset.get('name', 'this dataset')}",
                "Compute bounded profile metrics before proposing any data-cleaning changes.",
                "data_quality",
                [{
                    "source": "dataset_metadata",
                    "detail": f"Verified ingestion status is {dataset.get('status')}; the profile has not been computed by this recommendation.",
                }],
                "HIGH",
                "Establish measured null, distinct, duplicate, and outlier baselines.",
                arguments={"dataset_id": dataset_id},
            )

    selected_asset = context.get("selected_asset")
    selected_table_id = selected_asset.get("table_id") if selected_asset else None
    if page_type == "quality" and not selected_table_id:
        tables = context.get("tables", [])
        selected_table_id = tables[0].get("id") if tables else None
    if page_type == "quality" and selected_table_id:
        profile = selected_asset.get("profile") if selected_asset else None
        statistics = profile.get("statistics", {}) if isinstance(profile, dict) else {}
        columns_with_nulls = [
            name for name, stats in statistics.items()
            if isinstance(stats, dict) and isinstance(stats.get("null_count"), int) and stats["null_count"] > 0
        ] if isinstance(statistics, dict) else []
        if columns_with_nulls:
            add(
                "suggest_cleaning_transformations",
                "Review columns with measured nulls",
                "Draft a safe cleaning transformation for review; no data is changed by this suggestion.",
                "data_quality",
                [{
                    "source": "cached_profile",
                    "detail": f"{len(columns_with_nulls)} profiled column(s) have measured null values.",
                }],
                "HIGH",
                "Prepare a validated transformation draft based on existing profile metrics.",
                "MEDIUM",
                {"table_id": selected_table_id},
            )
        elif not profile:
            add(
                "analyze_data_quality",
                "Measure this table's quality",
                "Run the existing read-only quality summary before considering any cleanup.",
                "data_quality",
                [{"source": "catalog_profile", "detail": "No cached profile is available for the selected table."}],
                "HIGH",
                "Obtain actual quality metrics for this lakehouse table.",
                arguments={"table_id": selected_table_id},
            )

    if page_type == "catalog" and selected_asset and not selected_asset.get("description"):
        asset_id = selected_asset.get("id")
        if asset_id:
            add(
                "draft_catalog_metadata",
                "Document this catalog asset",
                "Add a reviewed description to improve asset discoverability.",
                "catalog",
                [{"source": "catalog_metadata", "detail": "The selected asset currently has no description."}],
                "HIGH",
                "Improve discoverability for workspace members.",
                "MEDIUM",
                {"catalog_asset_id": asset_id},
            )

    if page_type in {"pipelines", "dashboard"}:
        failed = [
            item for item in context.get("recent_pipelines", [])
            if item.get("status") == "FAILED"
        ]
        if failed:
            pipeline = failed[0]
            add(
                "diagnose_pipeline_failure",
                "Investigate the latest pipeline failure",
                "Review the recorded failure classification before retrying or changing the pipeline.",
                "pipeline",
                [{
                    "source": "pipeline_run",
                    "detail": f"{pipeline.get('name', 'Pipeline')} most recently reported FAILED"
                    + (f" ({pipeline['failure_class']})" if pipeline.get("failure_class") else "."),
                }],
                "HIGH",
                "Identify a likely cause without retrying or modifying the pipeline.",
                arguments={"pipeline_name": pipeline.get("name")},
            )

    if page_type in {"catalog", "lineage", "lakehouse"} and selected_asset:
        lineage = context.get("lineage", [])
        if lineage:
            add(
                "explain_lineage",
                "Explain this asset's lineage",
                "Summarize the recorded upstream and downstream relationships.",
                "lineage",
                [{
                    "source": "lineage_edges",
                    "detail": f"{len(lineage)} recorded relationship(s) are available for this asset.",
                }],
                "HIGH",
                "Clarify the observed dependency path without inferring unrecorded relationships.",
                arguments={"catalog_asset_id": selected_asset.get("id")},
            )

    if page_type == "sql":
        add(
            "explain_sql",
            "Review the current SQL",
            "Explain the query or identify potential issues without executing it. The current query is included only in chat requests.",
            "sql",
            [{"source": "page_context", "detail": "The SQL Workspace is active."}],
            "HIGH",
            "Help the user understand query behavior while preserving read-only safeguards.",
        )

    if page_type == "audit" and context.get("recent_activity"):
        activity_count = len(context["recent_activity"])
        add(
            "summarize_workspace_activity",
            "Summarize recent workspace activity",
            "Summarize the bounded audit actions visible to this workspace member.",
            "governance",
            [{"source": "audit_logs", "detail": f"{activity_count} recent authorized audit event(s) are available."}],
            "HIGH",
            "Make recent workspace activity easier to review.",
        )

    return recommendations[:3]
