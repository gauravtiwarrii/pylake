"use client";

import { type FormEvent, type ReactNode, useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { api, streamApi } from "@/lib/api";
import { type AIPageContextValue, pageTypeFromPath } from "@/components/ai-page-context";

type Conversation = {
  id: string;
  title: string;
  updated_at: string;
};

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

type Context = Omit<AIPageContextValue, "pathname">;

type Recommendation = {
  id: string;
  title: string;
  description: string;
  category: string;
  evidence: { source: string; detail: string }[];
  confidence: "LOW" | "MEDIUM" | "HIGH";
  expected_impact: string;
  proposed_action: { tool: string; arguments: Record<string, unknown> };
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  required_permissions: string[];
  approval_required: boolean;
  status: "PROPOSED" | "ACCEPTED" | "REJECTED";
};

type Draft = {
  kind: string;
  value: Record<string, unknown>;
};

type Mode = "simple" | "detailed" | "technical";

type Props = {
  workspaceId: string;
  compact?: boolean;
  onClose?: () => void;
  pageContext?: AIPageContextValue;
};

function subscribeToSearchString(onChange: () => void) {
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
}

function getSearchString() {
  return typeof window === "undefined" ? "" : window.location.search;
}

function getServerSearchString() {
  return "";
}

function renderInlineMarkdown(text: string, keyPrefix: string): ReactNode[] {
  return text.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*\n]+\*)/g).map((part, index) => {
    const key = `${keyPrefix}-${index}`;
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={key} className="rounded bg-[var(--surface-raised)] px-1 py-0.5 font-mono text-[0.92em]">{part.slice(1, -1)}</code>;
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("*") && part.endsWith("*")) {
      return <em key={key}>{part.slice(1, -1)}</em>;
    }
    return part;
  });
}

function renderMarkdownText(text: string, keyPrefix: string): ReactNode[] {
  const lines = text.split(/\r?\n/);
  const blocks: ReactNode[] = [];
  let index = 0;
  let blockIndex = 0;
  const isListItem = (line: string) => /^\s*[-*+]\s+/.test(line);
  const isOrderedItem = (line: string) => /^\s*\d+\.\s+/.test(line);
  const isSpecialLine = (line: string) =>
    /^#{1,3}\s+/.test(line) || isListItem(line) || isOrderedItem(line) || /^>\s?/.test(line);

  while (index < lines.length) {
    const line = lines[index];
    const key = `${keyPrefix}-${blockIndex++}`;
    if (!line.trim()) {
      index += 1;
      continue;
    }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      const Heading = heading[1].length === 1 ? "h2" : "h3";
      blocks.push(<Heading key={key} className="font-semibold leading-6">{renderInlineMarkdown(heading[2], key)}</Heading>);
      index += 1;
      continue;
    }
    if (isListItem(line) || isOrderedItem(line)) {
      const ordered = isOrderedItem(line);
      const items: ReactNode[] = [];
      while (index < lines.length && (ordered ? isOrderedItem(lines[index]) : isListItem(lines[index]))) {
        const item = lines[index].replace(ordered ? /^\s*\d+\.\s+/ : /^\s*[-*+]\s+/, "");
        items.push(<li key={`${key}-${items.length}`}>{renderInlineMarkdown(item, `${key}-${items.length}`)}</li>);
        index += 1;
      }
      const List = ordered ? "ol" : "ul";
      blocks.push(<List key={key} className={`space-y-1 pl-5 ${ordered ? "list-decimal" : "list-disc"}`}>{items}</List>);
      continue;
    }
    if (/^>\s?/.test(line)) {
      blocks.push(<blockquote key={key} className="border-l-2 border-[var(--border-strong)] pl-3 text-[var(--muted)]">{renderInlineMarkdown(line.replace(/^>\s?/, ""), key)}</blockquote>);
      index += 1;
      continue;
    }
    const paragraph = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !isSpecialLine(lines[index])) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push(<p key={key} className="whitespace-pre-wrap">{renderInlineMarkdown(paragraph.join("\n"), key)}</p>);
  }
  return blocks;
}

function renderAssistantMarkdown(content: string): ReactNode[] {
  const blocks: ReactNode[] = [];
  const codeFence = /```([a-zA-Z0-9_+-]*)\r?\n([\s\S]*?)```/g;
  let cursor = 0;
  let match: RegExpExecArray | null;
  let blockIndex = 0;
  while ((match = codeFence.exec(content)) !== null) {
    blocks.push(...renderMarkdownText(content.slice(cursor, match.index), `markdown-${blockIndex}`));
    blocks.push(
      <pre key={`code-${blockIndex}`} className="max-w-full overflow-x-auto rounded-lg bg-[var(--surface-raised)] p-3 text-xs leading-5">
        <code className={match[1] ? `language-${match[1]} font-mono` : "font-mono"}>{match[2]}</code>
      </pre>,
    );
    cursor = match.index + match[0].length;
    blockIndex += 1;
  }
  blocks.push(...renderMarkdownText(content.slice(cursor), `markdown-${blockIndex}`));
  return blocks;
}

export function AICopilotChat({ workspaceId, compact = false, onClose, pageContext }: Props) {
  const pathname = usePathname();
  const searchString = useSyncExternalStore(
    subscribeToSearchString,
    getSearchString,
    getServerSearchString,
  );
  const searchParams = new URLSearchParams(searchString);
  const [status, setStatus] = useState<{ configured: boolean; provider: string; model: string } | null>(null);
  const [usage, setUsage] = useState<{ requests: number; input_tokens: number; output_tokens: number; tokens_reported: boolean } | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [prompt, setPrompt] = useState("");
  const [mode, setMode] = useState<Mode>("detailed");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [retryPrompt, setRetryPrompt] = useState("");
  const [copiedMessageId, setCopiedMessageId] = useState("");
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [recommendationsLoading, setRecommendationsLoading] = useState(false);
  const [recommendationError, setRecommendationError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const queryDatasetId = searchParams.get("dataset_id") || undefined;
  const queryTableId = searchParams.get("table_id") || undefined;
  const queryPipelineId = searchParams.get("pipeline_id") || undefined;
  const querySql = searchParams.get("sql_text") || undefined;
  const queryPageType = queryDatasetId
    ? "dataset"
    : queryTableId
      ? "lakehouse"
      : queryPipelineId
        ? "pipelines"
        : querySql
          ? "sql"
          : undefined;
  const context: Context = {
    page_type: pageContext?.page_type && pageContext.page_type !== "ai"
      ? pageContext.page_type
      : queryPageType ?? pageContext?.page_type ?? pageTypeFromPath(pathname),
    active_view: pageContext?.active_view,
    dataset_id: pageContext?.dataset_id || queryDatasetId,
    table_id: pageContext?.table_id || queryTableId,
    pipeline_id: pageContext?.pipeline_id || queryPipelineId,
    catalog_asset_id: pageContext?.catalog_asset_id || searchParams.get("catalog_asset_id") || undefined,
    sql_text: pageContext?.sql_text || querySql,
  };

  const loadRecommendations = useCallback(async () => {
    setRecommendationsLoading(true);
    setRecommendationError("");
    const result = await api<Recommendation[]>(
      `/api/v1/workspaces/${workspaceId}/ai/recommendations`,
      {
        method: "POST",
        body: JSON.stringify({
          page_type: context.page_type,
          dataset_id: context.dataset_id,
          table_id: context.table_id,
          pipeline_id: context.pipeline_id,
          catalog_asset_id: context.catalog_asset_id,
        }),
      },
    );
    setRecommendationsLoading(false);
    if (result.error) setRecommendationError(result.error);
    else setRecommendations(result.data ?? []);
  }, [
    workspaceId,
    setRecommendationsLoading,
    setRecommendationError,
    setRecommendations,
    context.page_type,
    context.dataset_id,
    context.table_id,
    context.pipeline_id,
    context.catalog_asset_id,
  ]);

  useEffect(() => {
    const timeout = window.setTimeout(() => void loadRecommendations(), 0);
    return () => window.clearTimeout(timeout);
  }, [loadRecommendations]);

  const loadConversations = useCallback(async () => {
    const result = await api<Conversation[]>(`/api/v1/workspaces/${workspaceId}/ai/conversations`);
    if (result.error) setError(result.error);
    else setConversations(result.data ?? []);
  }, [workspaceId, setError, setConversations]);

  const loadUsage = useCallback(async () => {
    const result = await api<{ requests: number; input_tokens: number; output_tokens: number; tokens_reported: boolean }>(
      `/api/v1/workspaces/${workspaceId}/ai/usage`,
    );
    if (result.data) setUsage(result.data);
  }, [workspaceId, setUsage]);

  useEffect(() => {
    let active = true;
    const load = async () => {
      const [statusResult, conversationResult, usageResult] = await Promise.all([
        api<{ configured: boolean; provider: string; model: string }>(`/api/v1/workspaces/${workspaceId}/ai/status`),
        api<Conversation[]>(`/api/v1/workspaces/${workspaceId}/ai/conversations`),
        api<{ requests: number; input_tokens: number; output_tokens: number; tokens_reported: boolean }>(`/api/v1/workspaces/${workspaceId}/ai/usage`),
      ]);
      if (!active) return;
      if (statusResult.error) setError(statusResult.error);
      else setStatus(statusResult.data ?? null);
      if (conversationResult.error) setError(conversationResult.error);
      else setConversations(conversationResult.data ?? []);
      if (usageResult.data) setUsage(usageResult.data);
      setLoading(false);
    };
    void load();
    return () => {
      active = false;
    };
  }, [workspaceId]);

  useEffect(() => {
    if (!conversationId) return;
    let active = true;
    const load = async () => {
      const result = await api<{ messages: Message[] }>(
        `/api/v1/workspaces/${workspaceId}/ai/conversations/${conversationId}`,
      );
      if (!active) return;
      if (result.error) setError(result.error);
      else setMessages(result.data?.messages ?? []);
    };
    void load();
    return () => {
      active = false;
    };
  }, [conversationId, workspaceId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const startNewConversation = () => {
    if (sending) return;
    setConversationId("");
    setMessages([]);
    setError("");
    setRetryPrompt("");
  };

  const sendPrompt = async (cleanPrompt: string) => {
    if (!cleanPrompt || sending) return;
    setError("");
    setRetryPrompt("");
    setSending(true);
    setPrompt("");
    const controller = new AbortController();
    controllerRef.current = controller;
    const localId = `local-${Date.now()}`;
    const assistantId = `${localId}-assistant`;
    let nextConversationId = conversationId;
    setMessages((current) => [
      ...current,
      { id: `${localId}-user`, role: "user", content: cleanPrompt },
      { id: assistantId, role: "assistant", content: "" },
    ]);

    try {
      const response = await streamApi(`/api/v1/workspaces/${workspaceId}/ai/chat`, {
        ...context,
        prompt: cleanPrompt,
        conversation_id: conversationId || undefined,
        mode,
      }, controller.signal);
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? "The request could not be completed.");
      }
      if (!response.body) throw new Error("The AI stream is unavailable.");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const processEvent = (block: string) => {
        let event = "";
        let data = "";
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          if (line.startsWith("data:")) data += line.slice(5).trim();
        }
        if (!event || !data) return;
        const payload = JSON.parse(data) as { conversation_id?: string; text?: string; message?: string };
        if (event === "meta" && payload.conversation_id) nextConversationId = payload.conversation_id;
        if (event === "delta" && payload.text) {
          setMessages((current) => current.map((message) =>
            message.id === assistantId
              ? { ...message, content: message.content + payload.text }
              : message,
          ));
        }
        if (event === "error") throw new Error(payload.message ?? "The AI response could not be completed.");
      };
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const blocks = buffer.split(/\r?\n\r?\n/);
        buffer = blocks.pop() ?? "";
        for (const block of blocks) processEvent(block);
        if (done) break;
      }
      if (buffer.trim()) processEvent(buffer);
      setConversationId(nextConversationId);
      await loadConversations();
      await loadUsage();
    } catch (requestError) {
      const stopped = controller.signal.aborted;
      setError(stopped
        ? "Generation stopped. The partial answer was discarded."
        : requestError instanceof Error
          ? requestError.message
          : "The AI response could not be completed.");
      setRetryPrompt(cleanPrompt);
      setMessages((current) => current.filter((message) => message.id !== assistantId));
      if (nextConversationId) {
        setConversationId(nextConversationId);
        await loadConversations();
      }
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
      setSending(false);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void sendPrompt(prompt.trim());
  };

  const copyResponse = async (message: Message) => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopiedMessageId(message.id);
      window.setTimeout(() => setCopiedMessageId(""), 1500);
    } catch {
      setError("Could not copy the response to the clipboard.");
    }
  };

  const removeConversation = async (id: string) => {
    const result = await api(`/api/v1/workspaces/${workspaceId}/ai/conversations/${id}`, { method: "DELETE" });
    if (result.error) setError(result.error);
    else {
      setConversations((current) => current.filter((item) => item.id !== id));
      if (conversationId === id) startNewConversation();
    }
  };

  const recordRecommendationDecision = async (
    recommendation: Recommendation,
    decision: "ACCEPTED" | "REJECTED",
  ) => {
    const result = await api<Recommendation>(
      `/api/v1/workspaces/${workspaceId}/ai/recommendations/${recommendation.id}/feedback`,
      {
        method: "POST",
        body: JSON.stringify({ decision }),
      },
    );
    if (result.error) setRecommendationError(result.error);
    else {
      setRecommendations((current) => current.map((item) =>
        item.id === recommendation.id ? result.data ?? item : item,
      ));
    }
  };

  const runDraftAction = async (kind: "profile" | "sql" | "transformation" | "pipeline") => {
    if (drafting) return;
    setError("");
    setDraft(null);
    if (kind !== "profile" && !prompt.trim()) {
      setError("Enter a request before generating a draft.");
      return;
    }
    let path: string;
    let body: Record<string, unknown>;
    if (kind === "profile") {
      if (!context.dataset_id) return;
      path = `/api/v1/workspaces/${workspaceId}/ai/datasets/${context.dataset_id}/analyze`;
      body = {};
    } else if (kind === "sql") {
      path = `/api/v1/workspaces/${workspaceId}/ai/sql/generate`;
      body = { prompt: prompt.trim(), sql_text: context.sql_text };
    } else if (kind === "transformation") {
      path = `/api/v1/workspaces/${workspaceId}/ai/transformations/generate`;
      body = { prompt: prompt.trim(), dataset_id: context.dataset_id, table_id: context.table_id };
    } else {
      path = `/api/v1/workspaces/${workspaceId}/ai/pipelines/generate`;
      body = { prompt: prompt.trim(), dataset_id: context.dataset_id };
    }
    setDrafting(true);
    try {
      const result = await api<Record<string, unknown>>(path, {
        method: "POST",
        ...(kind === "profile" ? {} : { body: JSON.stringify(body) }),
      });
      if (result.error) setError(result.error);
      else {
        setDraft({ kind, value: result.data ?? {} });
        await loadUsage();
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "The request could not be completed.");
    } finally {
      setDrafting(false);
    }
  };

  return (
    <div className={`flex min-h-0 ${compact ? "h-[min(68vh,620px)] flex-col" : "min-h-[calc(100vh-64px)]"}`}>
      {!compact && (
        <aside className="hidden w-72 shrink-0 border-r border-[var(--border)] bg-[var(--surface)] p-4 md:block">
          <button onClick={startNewConversation} disabled={sending} className="h-10 w-full rounded-lg border border-[var(--border-strong)] text-sm font-medium hover:bg-[var(--surface-hover)] disabled:opacity-50">
            New conversation
          </button>
          <p className="mb-2 mt-6 text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">Recent conversations</p>
          <div className="space-y-1">
            {conversations.map((conversation) => (
              <div key={conversation.id} className={`group flex items-center rounded-lg ${conversationId === conversation.id ? "bg-[var(--accent-soft)]" : "hover:bg-[var(--surface-hover)]"}`}>
                <button onClick={() => { setMessages([]); setConversationId(conversation.id); }} className="min-w-0 flex-1 px-3 py-2.5 text-left">
                  <span className="block truncate text-xs">{conversation.title}</span>
                  <span className="mt-1 block text-[10px] text-[var(--muted)]">{new Date(conversation.updated_at).toLocaleDateString()}</span>
                </button>
                <button onClick={() => void removeConversation(conversation.id)} aria-label={`Delete ${conversation.title}`} className="mr-2 hidden rounded px-1.5 py-1 text-[10px] text-[var(--muted)] hover:text-[var(--danger)] group-hover:block">Delete</button>
              </div>
            ))}
            {!loading && conversations.length === 0 && <p className="px-2 py-3 text-xs text-[var(--muted)]">Your conversations will appear here.</p>}
          </div>
        </aside>
      )}

      <section className="flex min-h-0 min-w-0 flex-1 flex-col">
        {!compact && (
          <header className="flex items-center justify-between border-b border-[var(--border)] px-5 py-4 md:px-8">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--accent)]">Workspace-aware assistant</p>
              <h1 className="mt-1 text-xl font-semibold tracking-tight">AI Copilot</h1>
              <p className="mt-1 text-xs text-[var(--muted)]">
                {status?.configured ? `${status.provider} · ${status.model}` : "Provider not configured"}
              </p>
              {usage && <p className="mt-1 text-[10px] text-[var(--muted)]">{usage.requests} requests in 30 days · {usage.tokens_reported ? `${(usage.input_tokens + usage.output_tokens).toLocaleString()} reported tokens` : "provider token usage unavailable"}</p>}
            </div>
            {onClose && <button onClick={onClose} className="text-xs text-[var(--muted)] hover:text-[var(--foreground)]">Close</button>}
          </header>
        )}

        <div ref={scrollRef} className={`min-h-0 flex-1 space-y-4 overflow-y-auto ${compact ? "px-3 py-3" : "mx-auto w-full max-w-4xl px-4 py-6 md:px-8"}`}>
          {loading && <p className="text-sm text-[var(--muted)]">Loading Copilot...</p>}
          {!loading && !status?.configured && (
            <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 text-sm">
              AI is currently unavailable. Configure `AI_PROVIDER`, `AI_MODEL`, and the provider credentials on the server.
            </div>
          )}
          {error && (
            <div role="alert" className="flex items-center justify-between gap-3 rounded-lg border border-[color-mix(in_srgb,var(--danger)_35%,transparent)] bg-[color-mix(in_srgb,var(--danger)_8%,var(--surface))] px-3 py-2 text-xs text-[var(--danger)]">
              <span>{error}</span>
              {retryPrompt && !sending && (
                <button type="button" onClick={() => void sendPrompt(retryPrompt)} className="shrink-0 rounded border border-current px-2 py-1 font-medium hover:bg-[var(--surface)]">
                  Retry
                </button>
              )}
            </div>
          )}
          {recommendationError && (
            <p role="status" className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs text-[var(--muted)]">
              Contextual suggestions are unavailable: {recommendationError}
            </p>
          )}
          {(recommendationsLoading || recommendations.length > 0) && (
            <section aria-label="Contextual recommendations" className="space-y-2">
              <div className="flex items-center justify-between">
                <h2 className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">Grounded recommendations</h2>
                {recommendationsLoading && <span className="text-[10px] text-[var(--muted)]">Checking context...</span>}
              </div>
              {recommendations.map((recommendation) => (
                <article key={recommendation.id} className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="text-xs font-semibold">{recommendation.title}</h3>
                    <span className="shrink-0 rounded-full border border-[var(--border)] px-2 py-0.5 text-[9px] text-[var(--muted)]">
                      {recommendation.risk_level} risk
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] leading-5 text-[var(--muted)]">{recommendation.description}</p>
                  <ul className="mt-2 space-y-1">
                    {recommendation.evidence.map((item, index) => (
                      <li key={`${item.source}-${index}`} className="text-[10px] leading-4 text-[var(--muted)]">
                        <span className="font-medium text-[var(--foreground)]">{item.source}:</span> {item.detail}
                      </li>
                    ))}
                  </ul>
                  <p className="mt-2 text-[10px] text-[var(--muted)]">
                    {recommendation.expected_impact} · Confidence: {recommendation.confidence}
                    {recommendation.approval_required ? " · Review and explicit approval required before applying" : ""}
                  </p>
                  <p className="mt-1 text-[9px] text-[var(--muted)]">
                    Suggested capability: {recommendation.proposed_action.tool}
                    {recommendation.required_permissions.length
                      ? ` · Applying requires ${recommendation.required_permissions.join(", ")}`
                      : ""}
                  </p>
                  {recommendation.status === "PROPOSED" ? (
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={() => void recordRecommendationDecision(recommendation, "ACCEPTED")}
                        className="rounded border border-[var(--border-strong)] px-2 py-1 text-[9px] hover:border-[var(--accent)]"
                      >
                        Accept suggestion
                      </button>
                      <button
                        type="button"
                        onClick={() => void recordRecommendationDecision(recommendation, "REJECTED")}
                        className="rounded border border-[var(--border)] px-2 py-1 text-[9px] text-[var(--muted)] hover:text-[var(--foreground)]"
                      >
                        Dismiss
                      </button>
                      <span className="text-[9px] text-[var(--muted)]">Recording a decision does not run an action.</span>
                    </div>
                  ) : (
                    <p className="mt-2 text-[9px] text-[var(--muted)]">Decision recorded: {recommendation.status.toLowerCase()}.</p>
                  )}
                </article>
              ))}
            </section>
          )}
          {messages.length === 0 && (
            <div className="rounded-xl border border-dashed border-[var(--border-strong)] bg-[var(--surface)] px-5 py-8 text-center">
              <p className="text-sm font-medium">What would you like to understand?</p>
              <p className="mx-auto mt-2 max-w-md text-xs leading-5 text-[var(--muted)]">
                Ask about authorized workspace metadata, profile a dataset, or request a SQL or pipeline draft. Suggestions are never executed automatically.
              </p>
              <div className="mt-4 flex flex-wrap justify-center gap-2">
                {(context.page_type === "sql"
                  ? ["Explain the current SQL", "Help debug this query"]
                  : context.page_type === "pipelines"
                    ? ["Diagnose the latest pipeline failure", "Explain this pipeline's steps"]
                    : context.page_type === "quality"
                      ? ["Explain these quality metrics", "Suggest safe cleaning checks"]
                      : context.page_type === "lineage"
                        ? ["Explain upstream and downstream dependencies", "What impact could a schema change have?"]
                        : context.page_type === "catalog"
                          ? ["Explain this asset's schema", "Improve its catalog description"]
                          : context.page_type === "audit"
                            ? ["Summarize recent workspace activity", "Explain these audit actions"]
                            : context.dataset_id
                              ? ["Summarize this dataset", "Suggest data-quality checks"]
                              : context.page_type === "dashboard"
                                ? ["Summarize workspace health", "What should I review next?"]
                                : ["Summarize this workspace", "Which tables are available?"]
                ).map((suggestion) => (
                  <button key={suggestion} onClick={() => setPrompt(suggestion)} className="rounded-full border border-[var(--border)] px-3 py-1.5 text-[10px] text-[var(--muted)] hover:border-[var(--border-strong)] hover:text-[var(--foreground)]">
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((message) => (
            <article key={message.id} className={`max-w-[92%] rounded-xl border px-3.5 py-3 text-sm leading-6 ${message.role === "user" ? "ml-auto border-[color-mix(in_srgb,var(--accent)_35%,var(--border))] bg-[var(--accent-soft)]" : "border-[var(--border)] bg-[var(--surface)]"}`}>
              <div className="mb-1 flex items-center justify-between gap-4">
                <p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">{message.role === "user" ? "You" : "PyLake Copilot"}</p>
                {message.role === "assistant" && message.content && (
                  <button type="button" onClick={() => void copyResponse(message)} className="shrink-0 text-[9px] text-[var(--muted)] hover:text-[var(--foreground)]">
                    {copiedMessageId === message.id ? "Copied" : "Copy"}
                  </button>
                )}
              </div>
              {message.content
                ? message.role === "assistant"
                  ? <div className="space-y-2 break-words">{renderAssistantMarkdown(message.content)}</div>
                  : <p className="whitespace-pre-wrap break-words">{message.content}</p>
                : sending && message.role === "assistant"
                  ? <p className="text-[var(--muted)]">Thinking...</p>
                  : null}
            </article>
          ))}
          {draft && (
            <section aria-label={`${draft.kind} draft result`} className="rounded-xl border border-[color-mix(in_srgb,var(--accent)_35%,var(--border))] bg-[var(--surface)] p-3">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-xs font-semibold capitalize text-[var(--accent)]">{draft.kind === "profile" ? "Dataset profile" : `${draft.kind} draft`}</p>
                <button onClick={() => setDraft(null)} className="text-[10px] text-[var(--muted)] hover:text-[var(--foreground)]">Dismiss</button>
              </div>
              {typeof draft.value.explanation === "string" && <p className="mb-2 whitespace-pre-wrap text-xs leading-5">{draft.value.explanation}</p>}
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-[var(--surface-raised)] p-3 font-mono text-[10px] leading-4 text-[var(--muted)]">{JSON.stringify(draft.kind === "profile" ? draft.value.profile : draft.value, null, 2)}</pre>
              {typeof draft.value.sql === "string" && (
                <Link href={`/workspaces/${workspaceId}/sql?sql_text=${encodeURIComponent(draft.value.sql)}`} className="mt-3 inline-flex h-8 items-center rounded-lg border border-[var(--border)] px-3 text-xs hover:border-[var(--border-strong)]">
                  Open in SQL Workspace
                </Link>
              )}
            </section>
          )}
        </div>

        <form onSubmit={submit} className={`border-t border-[var(--border)] bg-[var(--background)] ${compact ? "p-3" : "px-4 py-4 md:px-8"}`}>
          <div className={`mx-auto flex max-w-4xl items-end gap-2 rounded-xl border border-[var(--border-strong)] bg-[var(--surface)] p-2 focus-within:border-[var(--accent)] ${compact ? "" : "shadow-[var(--shadow-soft)]"}`}>
            <label className="sr-only" htmlFor="ai-response-mode">Response detail</label>
            <select id="ai-response-mode" value={mode} onChange={(event) => setMode(event.target.value as Mode)} className="h-9 shrink-0 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-2 text-[10px] text-[var(--muted)] outline-none focus:border-[var(--accent)]">
              <option value="simple">Simple</option>
              <option value="detailed">Detailed</option>
              <option value="technical">Technical</option>
            </select>
            <textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              maxLength={8000}
              rows={compact ? 2 : 3}
              aria-label="Message PyLake AI Copilot"
              placeholder="Ask about your workspace..."
              className="max-h-36 min-h-10 flex-1 resize-y bg-transparent px-2 py-2 text-sm outline-none placeholder:text-[var(--muted)]"
            />
            {sending ? (
              <button type="button" onClick={() => controllerRef.current?.abort()} className="h-9 shrink-0 rounded-lg border border-[var(--border-strong)] px-3 text-xs font-semibold hover:bg-[var(--surface-hover)]">
                Stop
              </button>
            ) : (
              <button type="submit" disabled={!prompt.trim() || !status?.configured} className="h-9 shrink-0 rounded-lg bg-[var(--accent)] px-3 text-xs font-semibold text-[var(--accent-foreground)] hover:bg-[var(--accent-strong)] disabled:cursor-not-allowed disabled:opacity-45">
                Send
              </button>
            )}
          </div>
          {status?.configured && (
            <div className="mx-auto mt-2 flex max-w-4xl flex-wrap gap-2">
              {context.dataset_id && <button type="button" onClick={() => void runDraftAction("profile")} disabled={drafting} className="rounded-md border border-[var(--border)] px-2.5 py-1.5 text-[10px] text-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40">{drafting ? "Working..." : "Analyze dataset"}</button>}
              <button type="button" onClick={() => void runDraftAction("sql")} disabled={!prompt.trim() || drafting} className="rounded-md border border-[var(--border)] px-2.5 py-1.5 text-[10px] text-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40">Generate SQL draft</button>
              {(context.dataset_id || context.table_id) && <button type="button" onClick={() => void runDraftAction("transformation")} disabled={!prompt.trim() || drafting} className="rounded-md border border-[var(--border)] px-2.5 py-1.5 text-[10px] text-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40">Generate transform draft</button>}
              <button type="button" onClick={() => void runDraftAction("pipeline")} disabled={!prompt.trim() || drafting} className="rounded-md border border-[var(--border)] px-2.5 py-1.5 text-[10px] text-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40">Generate pipeline draft</button>
            </div>
          )}
          <p className="mx-auto mt-2 max-w-4xl text-[10px] text-[var(--muted)]">Your prompt, selected conversation history, and bounded workspace metadata are sent to the configured provider. Avoid entering secrets; review suggestions before use.</p>
        </form>
      </section>
    </div>
  );
}
