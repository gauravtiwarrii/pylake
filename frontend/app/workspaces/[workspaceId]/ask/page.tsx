"use client";

import { use, useCallback, useEffect, useState, type FormEvent } from "react";
import { ArrowRight, Database, MessageSquareText, Send } from "lucide-react";
import { useAIPageContext } from "@/components/ai-page-context";
import { AskAnswerCard } from "@/components/ask/AskAnswerCard";
import type { AskAnswer, AskHistoryItem } from "@/components/ask/types";
import { api } from "@/lib/api";

type Dataset = { id: string; name: string; ingestion_status: string };
type LakehouseTable = { id: string; name: string; current_layer?: string };

export default function AskLakehousePage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const [question, setQuestion] = useState("");
  const [datasetId, setDatasetId] = useState("");
  const [tableId, setTableId] = useState("");
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [tables, setTables] = useState<LakehouseTable[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [history, setHistory] = useState<AskHistoryItem[]>([]);
  const [answer, setAnswer] = useState<AskAnswer | null>(null);
  const [loading, setLoading] = useState(true);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");

  useAIPageContext({ page_type: "ask", active_view: answer?.answer_type ?? "question", dataset_id: datasetId || undefined, table_id: tableId || undefined });

  const loadHistory = useCallback(async () => {
    const response = await api<AskHistoryItem[]>(`/api/v1/workspaces/${workspaceId}/ask/history`);
    if (response.data) setHistory(response.data);
  }, [workspaceId]);

  useEffect(() => {
    let active = true;
    async function load() {
      setLoading(true);
      const [promptResult, datasetResult, tableResult, historyResult] = await Promise.all([
        api<{ items: string[] }>(`/api/v1/workspaces/${workspaceId}/ask/suggestions?page_type=ask`),
        api<{ items: Dataset[] }>(`/api/v1/workspaces/${workspaceId}/datasets?page=1&page_size=100`),
        api<LakehouseTable[]>(`/api/v1/workspaces/${workspaceId}/lakehouse/tables`),
        api<AskHistoryItem[]>(`/api/v1/workspaces/${workspaceId}/ask/history`),
      ]);
      if (!active) return;
      const errors = [promptResult.error, datasetResult.error, tableResult.error, historyResult.error].filter(Boolean);
      if (errors.length) setError(errors.join(" "));
      setSuggestions(promptResult.data?.items ?? []);
      setDatasets(datasetResult.data?.items ?? []);
      setTables(tableResult.data ?? []);
      setHistory(historyResult.data ?? []);
      setLoading(false);
    }
    void load();
    return () => { active = false; };
  }, [workspaceId]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalized = question.trim();
    if (!normalized || asking) return;
    setAsking(true);
    setError("");
    setAnswer(null);
    try {
      const response = await api<AskAnswer>(`/api/v1/workspaces/${workspaceId}/ask`, {
        method: "POST",
        body: JSON.stringify({ question: normalized, dataset_id: datasetId || null, table_id: tableId || null, execute: true }),
      });
      if (response.error || !response.data) {
        setError(response.error ?? "No answer was returned. Please try again.");
      } else {
        setAnswer(response.data);
        await loadHistory();
      }
    } catch {
      setError("Unable to reach Ask Lakehouse. Check your connection and try again.");
    } finally {
      setAsking(false);
    }
  };

  const refine = (candidate: { kind: "table" | "column"; name: string; table?: string }) => {
    if (candidate.kind === "table") {
      const matchingTable = tables.find((table) => table.name.toLowerCase() === candidate.name.toLowerCase());
      if (matchingTable) {
        setTableId(matchingTable.id);
        setDatasetId("");
      } else {
        setQuestion((current) => `${current} in ${candidate.name}`);
      }
      return;
    }
    setQuestion((current) => `${current} using ${candidate.name}${candidate.table ? ` from ${candidate.table}` : ""}`);
  };

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 p-4 md:p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-[var(--accent)]"><MessageSquareText size={14} /> Workspace intelligence</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight">Ask Your Lakehouse</h2>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-[var(--muted)]">Ask questions about workspace metadata or query your lakehouse with validated, read-only SQL. Answers cite the records and tables they use.</p>
        </div>
        <span className="rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-1.5 text-xs text-[var(--muted)]">AI optional · workspace scoped</span>
      </header>

      <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-[var(--shadow-soft)] md:p-5">
        <form onSubmit={(event) => void submit(event)}>
          <label htmlFor="ask-question" className="mb-2 block text-sm font-medium">What would you like to know?</label>
          <textarea id="ask-question" value={question} onChange={(event) => setQuestion(event.target.value)} maxLength={4000} rows={3} placeholder="Which products generated the highest revenue?" className="w-full resize-y rounded-xl border border-[var(--border)] bg-[var(--surface-raised)] px-4 py-3 text-sm outline-none placeholder:text-[var(--muted)] focus:border-[var(--accent)]" />
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-medium text-[var(--muted)]">Dataset scope <span className="font-normal">· optional</span>
              <select aria-label="Optional dataset scope" value={datasetId} onChange={(event) => setDatasetId(event.target.value)} className="mt-1.5 h-10 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-3 text-sm text-[var(--foreground)]">
                <option value="">All available datasets</option>
                {datasets.map((dataset) => <option key={dataset.id} value={dataset.id} disabled={dataset.ingestion_status !== "COMPLETED"}>{dataset.name} · {dataset.ingestion_status}</option>)}
              </select>
            </label>
            <label className="text-xs font-medium text-[var(--muted)]">Lakehouse table <span className="font-normal">· optional</span>
              <select aria-label="Optional table scope" value={tableId} onChange={(event) => setTableId(event.target.value)} className="mt-1.5 h-10 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-3 text-sm text-[var(--foreground)]">
                <option value="">Any queryable table</option>
                {tables.map((table) => <option key={table.id} value={table.id}>{table.name}{table.current_layer ? ` · ${table.current_layer}` : ""}</option>)}
              </select>
            </label>
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <p className="text-[11px] text-[var(--muted)]">Queries are checked as read-only and limited to your workspace.</p>
            <button type="submit" disabled={asking || loading || !question.trim()} className="inline-flex h-10 items-center gap-2 rounded-lg bg-[var(--accent)] px-4 text-sm font-semibold text-[var(--accent-foreground)] hover:bg-[var(--accent-strong)] disabled:cursor-not-allowed disabled:opacity-60">{asking ? "Thinking…" : "Ask"}<Send size={14} /></button>
          </div>
        </form>
        {error && <p role="alert" className="mt-3 rounded-lg border border-[color-mix(in_srgb,var(--danger)_35%,var(--border))] bg-[color-mix(in_srgb,var(--danger)_8%,transparent)] p-3 text-xs text-[var(--danger)]">{error}</p>}
        <div className="mt-5">
          <h3 className="text-xs font-semibold text-[var(--muted)]">Suggested questions</h3>
          {loading ? <p className="mt-2 text-xs text-[var(--muted)]">Loading suggestions…</p> : suggestions.length ? <ul className="mt-2 flex flex-wrap gap-2">{suggestions.map((prompt) => <li key={prompt}><button type="button" onClick={() => setQuestion(prompt.replaceAll("<table>", "sales"))} className="rounded-full border border-[var(--border)] bg-[var(--surface-raised)] px-3 py-2 text-left text-xs hover:border-[var(--accent)]">{prompt.replaceAll("<table>", "sales")}</button></li>)}</ul> : <p className="mt-2 text-xs text-[var(--muted)]">No suggestions are available.</p>}
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <section aria-live="polite" className="min-w-0">
          {asking && <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6 text-sm text-[var(--muted)]">Validating workspace sources and preparing your answer…</div>}
          {!asking && answer && <AskAnswerCard answer={answer} workspaceId={workspaceId} onRefine={refine} />}
          {!asking && !answer && <div className="grid min-h-56 place-items-center rounded-2xl border border-dashed border-[var(--border-strong)] bg-[var(--surface)] p-6 text-center"><div><span className="mx-auto grid size-11 place-items-center rounded-xl bg-[var(--accent-soft)] text-[var(--accent)]"><Database size={18} /></span><h3 className="mt-3 text-sm font-medium">Your answer will appear here</h3><p className="mt-1 max-w-md text-xs leading-5 text-[var(--muted)]">Use a suggested question or ask about metadata, table schemas, lineage, quality, or your data.</p></div></div>}
        </section>

        <aside aria-label="Recent asks" className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4">
          <div className="flex items-center justify-between"><h2 className="text-sm font-semibold">Recent asks</h2><span className="text-[10px] text-[var(--muted)]">{history.length} / 30</span></div>
          {loading ? <p className="mt-4 text-xs text-[var(--muted)]">Loading history…</p> : history.length ? <ul className="mt-3 space-y-1">{history.map((item) => <li key={item.id}><button type="button" onClick={() => { setQuestion(item.question); setAnswer(null); }} className="group w-full rounded-lg p-2 text-left hover:bg-[var(--surface-hover)]"><span className="block line-clamp-2 text-xs leading-5">{item.question}</span><span className="mt-1 flex items-center justify-between text-[10px] text-[var(--muted)]"><span>{item.answer_type}</span><ArrowRight size={12} className="opacity-0 transition-opacity group-hover:opacity-100" /></span></button></li>)}</ul> : <p className="mt-4 text-xs leading-5 text-[var(--muted)]">Your recent questions will be listed here.</p>}
        </aside>
      </div>
    </main>
  );
}
