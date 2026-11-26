import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai.context import (
    WorkspaceResourceNotFound,
    build_workspace_context,
    redact_sql_literals,
    redacted_text,
)
from app.ai.drafts import (
    InvalidAIDraft,
    parse_json_object,
    validate_pipeline_draft,
    validate_transformation_draft,
)
from app.ai.prompts import build_chat_messages, build_task_messages
from app.ai.recommendations import build_recommendations
from app.ai.providers import (
    AICompletion,
    AIConfigurationError,
    AIProvider,
    AIProviderError,
    AIStreamChunk,
    get_provider,
    provider_status,
)
from app.ai.tools import available_tools
from app.api.dependencies import get_current_user
from app.api.v1.workspaces import membership
from app.core.audit import record_audit
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.rate_limit import check_database_rate_limit
from app.models.entities import (
    AIConversation,
    AIMessage,
    AIRecommendation,
    AIUsage,
    Dataset,
    User,
    utcnow,
)
from app.schemas.ai import (
    AIChatRequest,
    AIConversationDetailResponse,
    AIConversationResponse,
    AIDatasetAnalysisResponse,
    AIRecommendationFeedbackRequest,
    AIRecommendationResponse,
    AIRecommendationsRequest,
    AIPipelineDraftResponse,
    AIPipelineGenerateRequest,
    AISQLGenerateRequest,
    AISQLResponse,
    AISQLTextRequest,
    AIStatusResponse,
    AITransformationDraftResponse,
    AITransformationGenerateRequest,
    AIUsageResponse,
)
from app.services.catalog import ensure_dataset_asset, profile_asset
from app.storage.factory import get_storage
from app.engines.catalog_resolver import resolve_catalog
from app.engines.query_validator import SQLValidationError, validate_read_only_sql
from app.models.entities import DatasetStatus

logger = logging.getLogger("pylake.ai")
router = APIRouter(prefix="/workspaces", tags=["ai"])


def _configured_provider(settings: Settings) -> AIProvider:
    try:
        return get_provider(settings)
    except AIConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error


def _check_ai_limits(db: Session, workspace_id: UUID, user: User, settings: Settings) -> None:
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


def _audit_context(
    db: Session,
    workspace_id: UUID,
    user_id: UUID,
    resource_count: int,
    conversation_id: UUID | None = None,
) -> None:
    record_audit(
        db,
        workspace_id,
        user_id,
        "AI_CONTEXT_ACCESSED",
        "ai_context",
        conversation_id,
        {"resource_count": resource_count},
    )


def _context(
    db: Session,
    workspace_id: UUID,
    user: User,
    settings: Settings,
    **resource_ids: UUID | str | bool | None,
) -> tuple[dict[str, Any], int]:
    try:
        return build_workspace_context(
            db,
            workspace_id,
            user.id,
            settings,
            **resource_ids,
        )
    except WorkspaceResourceNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


def _save_usage(
    db: Session,
    workspace_id: UUID,
    user_id: UUID,
    provider: AIProvider,
    conversation_id: UUID | None,
    result: AICompletion | AIStreamChunk | None,
    result_status: str,
    duration_ms: int,
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


def _complete(
    db: Session,
    workspace_id: UUID,
    user: User,
    provider: AIProvider,
    messages: list[dict[str, str]],
    settings: Settings,
    conversation_id: UUID | None = None,
) -> tuple[AICompletion, int]:
    started = time.perf_counter()
    try:
        result = provider.complete(messages, settings.ai_max_output_tokens)
    except AIProviderError as error:
        duration = int((time.perf_counter() - started) * 1000)
        _save_usage(db, workspace_id, user.id, provider, conversation_id, None, "FAILED", duration)
        db.commit()
        logger.warning("AI provider request failed provider=%s", provider.name)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The AI provider request failed",
        ) from error
    return result, int((time.perf_counter() - started) * 1000)


def _store_generation(
    db: Session,
    workspace_id: UUID,
    user_id: UUID,
    provider: AIProvider,
    result: AICompletion,
    duration_ms: int,
    result_status: str = "SUCCESS",
) -> None:
    _save_usage(db, workspace_id, user_id, provider, None, result, result_status, duration_ms)
    db.commit()


def _json_event(event_name: str, data: dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=True)}\n\n"


def _workspace_conversation(
    db: Session,
    workspace_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
) -> AIConversation:
    conversation = db.query(AIConversation).filter(
        AIConversation.id == conversation_id,
        AIConversation.workspace_id == workspace_id,
        AIConversation.user_id == user_id,
    ).first()
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


@router.get("/{workspace_id}/ai/status", response_model=AIStatusResponse)
def ai_status(
    workspace_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str | bool]:
    membership(db, workspace_id, user.id)
    return provider_status(get_settings())


@router.post("/{workspace_id}/ai/chat")
def chat(
    workspace_id: UUID,
    payload: AIChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    member = membership(db, workspace_id, user.id)
    prompt = payload.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Message cannot be blank")
    settings = get_settings()
    if len(prompt) > settings.ai_max_input_chars // 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message exceeds the configured AI input limit",
        )
    provider = _configured_provider(settings)
    _check_ai_limits(db, workspace_id, user, settings)
    context, resource_count = _context(
        db,
        workspace_id,
        user,
        settings,
        dataset_id=payload.dataset_id,
        table_id=payload.table_id,
        pipeline_id=payload.pipeline_id,
        catalog_asset_id=payload.catalog_asset_id,
        page_type=payload.page_type,
        active_view=payload.active_view,
        include_audit=member.role.value in {"OWNER", "ADMIN"},
        query_text=payload.sql_text[: min(settings.ai_max_context_chars, settings.ai_max_input_chars // 3)] if payload.sql_text else None,
    )
    context["available_tools"] = [
        {"name": tool["name"], "read_only": tool["read_only"], "approval_required": tool["approval_required"]}
        for tool in available_tools(member.role.value, payload.page_type)
    ]

    conversation = (
        _workspace_conversation(db, workspace_id, user.id, payload.conversation_id)
        if payload.conversation_id
        else AIConversation(
            workspace_id=workspace_id,
            user_id=user.id,
            title=prompt.splitlines()[0][:200],
        )
    )
    is_new = conversation.id is None
    if is_new:
        db.add(conversation)
        db.flush()
    previous_messages = db.query(AIMessage).filter(
        AIMessage.conversation_id == conversation.id,
    ).order_by(AIMessage.created_at.desc()).limit(settings.ai_max_history_messages).all()
    new_user_message = AIMessage(
        conversation_id=conversation.id,
        role="user",
        content=prompt,
    )
    db.add(new_user_message)
    _audit_context(db, workspace_id, user.id, resource_count, conversation.id)
    db.commit()

    history = [
        {"role": item.role, "content": item.content}
        for item in reversed(previous_messages)
        if item.role in {"user", "assistant"}
    ]
    messages = build_chat_messages(
        prompt,
        context,
        history,
        payload.mode,
        settings.ai_max_input_chars,
    )
    conversation_id = conversation.id
    db.refresh(conversation)

    def stream_response() -> Iterator[str]:
        started = time.perf_counter()
        response_parts: list[str] = []
        latest_usage: AIStreamChunk | None = None
        provider_finished = False
        finalized = False
        stream = provider.stream(messages, settings.ai_max_output_tokens)
        try:
            yield _json_event("meta", {"conversation_id": str(conversation_id)})
            for chunk in stream:
                provider_finished = provider_finished or chunk.finished
                if chunk.input_tokens is not None or chunk.output_tokens is not None:
                    latest_usage = AIStreamChunk(
                        input_tokens=chunk.input_tokens if chunk.input_tokens is not None else (latest_usage.input_tokens if latest_usage else None),
                        output_tokens=chunk.output_tokens if chunk.output_tokens is not None else (latest_usage.output_tokens if latest_usage else None),
                    )
                if chunk.text:
                    response_parts.append(chunk.text)
                    yield _json_event("delta", {"text": chunk.text})
            answer = "".join(response_parts)
            if not provider_finished:
                raise AIProviderError("The provider stream ended before completion")
            if not answer.strip():
                raise AIProviderError("The provider returned an empty response")
            assistant = AIMessage(
                conversation_id=conversation_id,
                role="assistant",
                content=answer,
            )
            db.add(assistant)
            conversation.updated_at = utcnow()
            duration = int((time.perf_counter() - started) * 1000)
            _save_usage(db, workspace_id, user.id, provider, conversation_id, latest_usage, "SUCCESS", duration)
            db.commit()
            finalized = True
            yield _json_event("done", {
                "message_id": str(assistant.id),
                "input_tokens": latest_usage.input_tokens if latest_usage else None,
                "output_tokens": latest_usage.output_tokens if latest_usage else None,
            })
        except AIProviderError:
            duration = int((time.perf_counter() - started) * 1000)
            _save_usage(db, workspace_id, user.id, provider, conversation_id, latest_usage, "FAILED", duration)
            record_audit(db, workspace_id, user.id, "AI_PROVIDER_FAILURE", "ai_conversation", conversation_id)
            db.commit()
            finalized = True
            logger.warning("AI streaming request failed provider=%s", provider.name)
            yield _json_event("error", {"message": "The AI response could not be completed"})
        finally:
            close = getattr(stream, "close", None)
            if close:
                close()
            if not finalized:
                duration = int((time.perf_counter() - started) * 1000)
                _save_usage(db, workspace_id, user.id, provider, conversation_id, latest_usage, "INTERRUPTED", duration)
                db.commit()

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _recommendation_json(item: AIRecommendation) -> dict[str, Any]:
    return {
        "id": item.id,
        "page_type": item.page_type,
        "category": item.category,
        "title": item.title,
        "description": item.description,
        "evidence": item.evidence_json,
        "confidence": item.confidence,
        "expected_impact": item.expected_impact,
        "proposed_action": item.proposed_action_json,
        "risk_level": item.risk_level,
        "required_permissions": item.required_permissions_json,
        "approval_required": item.approval_required,
        "status": item.status,
        "created_at": item.created_at,
    }


@router.get("/{workspace_id}/ai/tools")
def list_ai_tools(
    workspace_id: UUID,
    page_type: str | None = Query(default=None, max_length=30),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, object]]:
    member = membership(db, workspace_id, user.id)
    return available_tools(member.role.value, page_type)


@router.post(
    "/{workspace_id}/ai/recommendations",
    response_model=list[AIRecommendationResponse],
)
def create_recommendations(
    workspace_id: UUID,
    payload: AIRecommendationsRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    member = membership(db, workspace_id, user.id)
    settings = get_settings()
    check_database_rate_limit(
        db,
        f"{workspace_id}:{user.id}",
        "ai_recommendations",
        attempts=settings.ai_rate_limit_requests,
        window_seconds=settings.ai_rate_limit_window_seconds,
    )
    context, resource_count = _context(
        db,
        workspace_id,
        user,
        settings,
        dataset_id=payload.dataset_id,
        table_id=payload.table_id,
        pipeline_id=payload.pipeline_id,
        catalog_asset_id=payload.catalog_asset_id,
        page_type=payload.page_type,
        active_view=payload.active_view,
        include_audit=member.role.value in {"OWNER", "ADMIN"},
        query_text=payload.sql_text[: min(settings.ai_max_context_chars, settings.ai_max_input_chars // 3)] if payload.sql_text else None,
    )
    _audit_context(db, workspace_id, user.id, resource_count)
    recommendations = build_recommendations(context, payload.page_type, member.role.value)
    rows = [
        AIRecommendation(
            workspace_id=workspace_id,
            user_id=user.id,
            page_type=payload.page_type,
            category=item["category"],
            title=item["title"],
            description=item["description"],
            evidence_json=item["evidence"],
            confidence=item["confidence"],
            expected_impact=item["expected_impact"],
            proposed_action_json=item["proposed_action"],
            risk_level=item["risk_level"],
            required_permissions_json=item["required_permissions"],
            approval_required=item["approval_required"],
        )
        for item in recommendations
    ]
    db.add_all(rows)
    db.commit()
    for row in rows:
        db.refresh(row)
    return [_recommendation_json(row) for row in rows]


@router.post(
    "/{workspace_id}/ai/recommendations/{recommendation_id}/feedback",
    response_model=AIRecommendationResponse,
)
def record_recommendation_feedback(
    workspace_id: UUID,
    recommendation_id: UUID,
    payload: AIRecommendationFeedbackRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    membership(db, workspace_id, user.id)
    recommendation = db.query(AIRecommendation).filter(
        AIRecommendation.id == recommendation_id,
        AIRecommendation.workspace_id == workspace_id,
        AIRecommendation.user_id == user.id,
    ).first()
    if not recommendation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found")
    if recommendation.status != "PROPOSED":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Recommendation feedback has already been recorded")
    recommendation.status = payload.decision
    recommendation.decision_at = utcnow()
    record_audit(
        db,
        workspace_id,
        user.id,
        f"AI_RECOMMENDATION_{payload.decision}",
        "ai_recommendation",
        recommendation.id,
        {"tool": recommendation.proposed_action_json.get("tool")},
    )
    db.commit()
    db.refresh(recommendation)
    return _recommendation_json(recommendation)


@router.get("/{workspace_id}/ai/conversations", response_model=list[AIConversationResponse])
def list_conversations(
    workspace_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AIConversation]:
    membership(db, workspace_id, user.id)
    return db.query(AIConversation).filter(
        AIConversation.workspace_id == workspace_id,
        AIConversation.user_id == user.id,
    ).order_by(AIConversation.updated_at.desc()).offset((page - 1) * page_size).limit(page_size).all()


@router.get(
    "/{workspace_id}/ai/conversations/{conversation_id}",
    response_model=AIConversationDetailResponse,
)
def get_conversation(
    workspace_id: UUID,
    conversation_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    membership(db, workspace_id, user.id)
    conversation = _workspace_conversation(db, workspace_id, user.id, conversation_id)
    messages = db.query(AIMessage).filter(
        AIMessage.conversation_id == conversation.id,
    ).order_by(AIMessage.created_at.asc()).limit(200).all()
    return {
        "id": conversation.id,
        "title": conversation.title,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
        "messages": messages,
    }


@router.delete(
    "/{workspace_id}/ai/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_conversation(
    workspace_id: UUID,
    conversation_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    membership(db, workspace_id, user.id)
    conversation = _workspace_conversation(db, workspace_id, user.id, conversation_id)
    record_audit(db, workspace_id, user.id, "AI_CONVERSATION_DELETED", "ai_conversation", conversation.id)
    db.delete(conversation)
    db.commit()


@router.get("/{workspace_id}/ai/usage", response_model=AIUsageResponse)
def usage(
    workspace_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, int | bool]:
    membership(db, workspace_id, user.id)
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=30)
    rows = db.query(AIUsage).filter(
        AIUsage.workspace_id == workspace_id,
        AIUsage.user_id == user.id,
        AIUsage.created_at >= since,
    ).all()
    input_tokens = sum(row.input_tokens or 0 for row in rows)
    output_tokens = sum(row.output_tokens or 0 for row in rows)
    return {
        "period_days": 30,
        "requests": len(rows),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "token_limit_per_day": get_settings().ai_daily_token_limit,
        "tokens_reported": any(row.input_tokens is not None or row.output_tokens is not None for row in rows),
    }


@router.post(
    "/{workspace_id}/ai/datasets/{dataset_id}/analyze",
    response_model=AIDatasetAnalysisResponse,
)
def analyze_dataset(
    workspace_id: UUID,
    dataset_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    membership(db, workspace_id, user.id)
    dataset = db.query(Dataset).filter(
        Dataset.id == dataset_id,
        Dataset.workspace_id == workspace_id,
    ).first()
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    if dataset.ingestion_status != DatasetStatus.COMPLETED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Dataset is not ready for analysis")

    settings = get_settings()
    _check_ai_limits(db, workspace_id, user, settings)
    asset = ensure_dataset_asset(db, workspace_id, dataset)
    try:
        profile = profile_asset(db, get_storage(), asset)
    except Exception as error:
        logger.error("AI dataset profile failed dataset_id=%s", dataset.id)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Dataset profiling could not complete",
        ) from error
    _audit_context(db, workspace_id, user.id, 1)
    db.commit()

    current_status = provider_status(settings)
    explanation = None
    ai_error = None
    if current_status["configured"]:
        provider = _configured_provider(settings)
        safe_statistics = {
            name: {
                key: value
                for key, value in item.items()
                if key in {"data_type", "null_count", "null_percentage", "distinct_count"}
            }
            for name, item in profile.get("statistics", {}).items()
        }
        verified_facts = {
            "row_count": profile.get("row_count"),
            "column_count": profile.get("column_count"),
            "sample_rows": profile.get("sample_rows"),
            "duplicate_rows_sampled": profile.get("duplicate_rows_sampled"),
            "numeric_outliers_sampled": profile.get("numeric_outliers_sampled", {}),
            "statistics": safe_statistics,
        }
        messages = build_task_messages(
            "Explain actual dataset profile metrics and suggest safe, reviewable cleaning checks",
            "Explain only the verified statistics below. State clearly that duplicate and outlier counts are from a bounded sample. Do not invent results or claim changes were applied.",
            verified_facts,
        )
        try:
            result, duration = _complete(db, workspace_id, user, provider, messages, settings)
            explanation = result.text
            _store_generation(db, workspace_id, user.id, provider, result, duration)
        except HTTPException as error:
            ai_error = str(error.detail)
    return {
        "dataset_id": dataset.id,
        "profile": profile,
        "explanation": explanation,
        "provider_available": bool(current_status["configured"]),
        "ai_error": ai_error,
    }


def _run_context_task(
    workspace_id: UUID,
    user: User,
    db: Session,
    settings: Settings,
    task: str,
    request: str,
    **resource_ids: UUID | None,
) -> tuple[AIProvider, Any, int]:
    provider = _configured_provider(settings)
    _check_ai_limits(db, workspace_id, user, settings)
    context, resource_count = _context(
        db,
        workspace_id,
        user,
        settings,
        **resource_ids,
    )
    _audit_context(db, workspace_id, user.id, resource_count)
    messages = build_task_messages(task, request, context)
    result, duration = _complete(db, workspace_id, user, provider, messages, settings)
    return provider, result, duration


@router.post("/{workspace_id}/ai/sql/generate", response_model=AISQLResponse)
def generate_sql(
    workspace_id: UUID,
    payload: AISQLGenerateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    membership(db, workspace_id, user.id)
    settings = get_settings()
    provider, result, duration = _run_context_task(
        workspace_id,
        user,
        db,
        settings,
        "Generate one read-only DuckDB SELECT query for this workspace",
        (
            f"{payload.prompt.strip()}\nReturn only JSON with keys sql and explanation. "
            "The sql value must contain exactly one SELECT or UNION query and may reference only listed workspace tables."
        ),
        query_text=payload.sql_text[: min(settings.ai_max_context_chars, settings.ai_max_input_chars // 3)] if payload.sql_text else None,
    )
    try:
        value = parse_json_object(result.text)
        sql = value.get("sql")
        explanation = value.get("explanation")
        if not isinstance(sql, str) or not isinstance(explanation, str):
            raise InvalidAIDraft("SQL draft fields were missing")
        table_names, _ = validate_read_only_sql(sql)
        resolve_catalog(db, workspace_id, table_names)
    except (InvalidAIDraft, SQLValidationError, KeyError) as error:
        _store_generation(db, workspace_id, user.id, provider, result, duration, "REJECTED")
        record_audit(db, workspace_id, user.id, "AI_SQL_DRAFT_REJECTED", "ai_draft", None)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Generated SQL did not pass workspace read-only validation",
        ) from error
    _store_generation(db, workspace_id, user.id, provider, result, duration)
    return {"sql": sql, "explanation": explanation, "validated": True}


def _explain_sql(
    workspace_id: UUID,
    payload: AISQLTextRequest,
    db: Session,
    user: User,
    task: str,
) -> dict[str, Any]:
    membership(db, workspace_id, user.id)
    settings = get_settings()
    sql_limit = min(settings.ai_max_context_chars, settings.ai_max_input_chars // 3)
    bounded_sql = payload.sql[:sql_limit]
    redacted_sql = redact_sql_literals(bounded_sql)[:sql_limit]
    request = f"Explain this SQL without executing it:\n{redacted_sql}"
    if payload.error:
        request += f"\n\nAssociated error (user-provided, redacted): {redacted_text(payload.error, 500)}"
    provider, result, duration = _run_context_task(
        workspace_id,
        user,
        db,
        settings,
        task,
        request,
        query_text=bounded_sql,
    )
    _store_generation(db, workspace_id, user.id, provider, result, duration)
    return {"sql": None, "explanation": result.text, "validated": False}


@router.post("/{workspace_id}/ai/sql/explain", response_model=AISQLResponse)
def explain_sql(
    workspace_id: UUID,
    payload: AISQLTextRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _explain_sql(workspace_id, payload, db, user, "Explain SQL syntax and behavior")


@router.post("/{workspace_id}/ai/sql/debug", response_model=AISQLResponse)
def debug_sql(
    workspace_id: UUID,
    payload: AISQLTextRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _explain_sql(workspace_id, payload, db, user, "Debug SQL using the provided SQL and error")


@router.post(
    "/{workspace_id}/ai/transformations/generate",
    response_model=AITransformationDraftResponse,
)
def generate_transformation(
    workspace_id: UUID,
    payload: AITransformationGenerateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    membership(db, workspace_id, user.id)
    settings = get_settings()
    provider, result, duration = _run_context_task(
        workspace_id,
        user,
        db,
        settings,
        "Create a validated PyLake lakehouse transformation suggestion",
        (
            f"{payload.prompt.strip()}\nReturn only JSON with transformation_type, configuration, "
            "target_layer, and explanation. Use only supported transformation types and columns."
        ),
        dataset_id=payload.dataset_id,
        table_id=payload.table_id,
    )
    try:
        value = parse_json_object(result.text)
        explanation = value.pop("explanation", None)
        if not isinstance(explanation, str):
            raise InvalidAIDraft("Transformation explanation was missing")
        draft = validate_transformation_draft(
            db,
            workspace_id,
            value,
            payload.dataset_id,
            payload.table_id,
        )
    except InvalidAIDraft as error:
        _store_generation(db, workspace_id, user.id, provider, result, duration, "REJECTED")
        record_audit(db, workspace_id, user.id, "AI_TRANSFORMATION_DRAFT_REJECTED", "ai_draft", None)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Generated transformation did not pass validation",
        ) from error
    _store_generation(db, workspace_id, user.id, provider, result, duration)
    return {
        "transformation_type": draft.transformation_type,
        "configuration": draft.configuration,
        "target_layer": draft.target_layer,
        "explanation": explanation,
    }


@router.post(
    "/{workspace_id}/ai/pipelines/generate",
    response_model=AIPipelineDraftResponse,
)
def generate_pipeline(
    workspace_id: UUID,
    payload: AIPipelineGenerateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    membership(db, workspace_id, user.id)
    settings = get_settings()
    provider, result, duration = _run_context_task(
        workspace_id,
        user,
        db,
        settings,
        "Create a valid PyLake pipeline draft without creating or running it",
        (
            f"{payload.prompt.strip()}\nReturn only JSON with name, description, steps, and explanation. "
            "The status must be DRAFT. Use only supported step types, operations, datasets, and tables."
        ),
        dataset_id=payload.dataset_id,
    )
    try:
        value = parse_json_object(result.text)
        explanation = value.pop("explanation", None)
        if not isinstance(explanation, str):
            raise InvalidAIDraft("Pipeline explanation was missing")
        draft = validate_pipeline_draft(db, workspace_id, value)
    except InvalidAIDraft as error:
        _store_generation(db, workspace_id, user.id, provider, result, duration, "REJECTED")
        record_audit(db, workspace_id, user.id, "AI_PIPELINE_DRAFT_REJECTED", "ai_draft", None)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Generated pipeline did not pass workspace validation",
        ) from error
    _store_generation(db, workspace_id, user.id, provider, result, duration)
    return {
        "name": draft.name,
        "description": draft.description,
        "status": "DRAFT",
        "steps": [step.model_dump(mode="json") for step in draft.steps],
        "explanation": explanation,
    }
