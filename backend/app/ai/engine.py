"""Shared non-streaming AI task engine.

One path for structured AI work: build bounded context → provider.complete
(with existing rate/usage limits) → strict JSON parse → caller validator.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai.context import WorkspaceResourceNotFound, build_workspace_context
from app.ai.drafts import InvalidAIDraft, parse_json_object
from app.ai.prompts import build_task_messages
from app.ai.providers import (
    AICompletion,
    AIConfigurationError,
    AIProvider,
    AIProviderError,
    get_provider,
)
from app.core.audit import record_audit
from app.core.config import Settings
from app.core.rate_limit import check_database_rate_limit
from app.models.entities import AIUsage, User


@dataclass(frozen=True)
class EngineResult:
    value: dict[str, Any]
    provider: AIProvider
    completion: AICompletion
    duration_ms: int
    resource_count: int
    context: dict[str, Any]


def _configured_provider(settings: Settings) -> AIProvider:
    try:
        return get_provider(settings)
    except AIConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error


def check_ai_limits(db: Session, workspace_id: UUID, user: User, settings: Settings) -> None:
    scope = f"{workspace_id}:{user.id}"
    check_database_rate_limit(
        db,
        scope,
        "ai_generation",
        attempts=settings.ai_rate_limit_requests,
        window_seconds=settings.ai_rate_limit_window_seconds,
    )
    if settings.ai_daily_token_limit == 0:
        return
    since = datetime.now(timezone.utc) - timedelta(days=1)
    total_tokens = db.query(
        func.coalesce(
            func.sum(
                func.coalesce(AIUsage.input_tokens, 0)
                + func.coalesce(AIUsage.output_tokens, 0)
            ),
            0,
        )
    ).filter(
        AIUsage.workspace_id == workspace_id,
        AIUsage.user_id == user.id,
        AIUsage.created_at >= since,
    ).scalar() or 0
    if total_tokens >= settings.ai_daily_token_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="The workspace AI token limit has been reached for today",
        )


def save_usage(
    db: Session,
    workspace_id: UUID,
    user_id: UUID,
    provider: AIProvider,
    result: AICompletion | None,
    result_status: str,
    duration_ms: int,
    conversation_id: UUID | None = None,
) -> None:
    db.add(AIUsage(
        workspace_id=workspace_id,
        user_id=user_id,
        conversation_id=conversation_id,
        provider=provider.name,
        model=provider.model,
        input_tokens=result.input_tokens if result else None,
        output_tokens=result.output_tokens if result else None,
        status=result_status,
        duration_ms=max(0, duration_ms),
    ))


def run_structured_task(
    db: Session,
    workspace_id: UUID,
    user: User,
    settings: Settings,
    *,
    task: str,
    request: str,
    validator: Callable[[dict[str, Any]], dict[str, Any]],
    provider: AIProvider | None = None,
    dataset_id: UUID | None = None,
    table_id: UUID | None = None,
    pipeline_id: UUID | None = None,
    catalog_asset_id: UUID | None = None,
    page_type: str = "ai",
    active_view: str | None = None,
    include_audit: bool = False,
    query_text: str | None = None,
    context_override: dict[str, Any] | None = None,
    audit_rejected_action: str | None = None,
    reject_detail: str = "Generated content did not pass validation",
) -> EngineResult:
    """Build context, call the provider, parse JSON, and run the caller validator."""
    provider = provider if provider is not None else _configured_provider(settings)
    check_ai_limits(db, workspace_id, user, settings)
    if context_override is not None:
        context, resource_count = context_override, 0
    else:
        try:
            context, resource_count = build_workspace_context(
                db,
                workspace_id,
                user.id,
                settings,
                dataset_id=dataset_id,
                table_id=table_id,
                pipeline_id=pipeline_id,
                catalog_asset_id=catalog_asset_id,
                page_type=page_type,
                active_view=active_view,
                include_audit=include_audit,
                query_text=query_text,
            )
        except WorkspaceResourceNotFound as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    record_audit(
        db,
        workspace_id,
        user.id,
        "AI_CONTEXT_ACCESSED",
        "ai_context",
        None,
        {"resource_count": resource_count},
    )
    messages = build_task_messages(task, request, context)
    started = time.perf_counter()
    try:
        completion = provider.complete(messages, settings.ai_max_output_tokens)
    except AIProviderError as error:
        duration = int((time.perf_counter() - started) * 1000)
        save_usage(db, workspace_id, user.id, provider, None, "FAILED", duration)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The AI provider request failed",
        ) from error
    duration = int((time.perf_counter() - started) * 1000)

    try:
        parsed = parse_json_object(completion.text)
        value = validator(parsed)
    except (InvalidAIDraft, ValueError, TypeError, KeyError) as error:
        save_usage(db, workspace_id, user.id, provider, completion, "REJECTED", duration)
        if audit_rejected_action:
            record_audit(db, workspace_id, user.id, audit_rejected_action, "ai_draft", None)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=reject_detail,
        ) from error

    save_usage(db, workspace_id, user.id, provider, completion, "SUCCESS", duration)
    db.commit()
    return EngineResult(
        value=value,
        provider=provider,
        completion=completion,
        duration_ms=duration,
        resource_count=resource_count,
        context=context,
    )
