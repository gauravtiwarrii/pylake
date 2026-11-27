"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAIPageContext } from "@/components/ai-page-context";
import { OverallTrustScore } from "./OverallTrustScore";
import { TrustMetricCard } from "./TrustMetricCard";
import { TrustRuleEditor } from "./TrustRuleEditor";
import type { TrustRule, TrustSnapshot } from "./types";

type Asset = { id: string; dataset_id?: string | null; lakehouse_table_id?: string | null; name: string };
type HistoryResponse = { items: TrustSnapshot[] };
type Explain = { ai_estimate: true; summary: string; recommendations: string[] };
export function TrustPassport({ workspaceId, assetId: initialAssetId, datasetId, tableId, canEdit = false }: { workspaceId: string; assetId?: string; datasetId?: string; tableId?: string; canEdit?: boolean }) {
  const [assetId, setAssetId] = useState(initialAssetId ?? ""); const [snapshot, setSnapshot] = useState<TrustSnapshot | null>(null); const [history, setHistory] = useState<TrustSnapshot[]>([]); const [rules, setRules] = useState<TrustRule[]>([]); const [freshness, setFreshness] = useState<number | null>(null); const [aiEnabled, setAiEnabled] = useState(false); const [explanation, setExplanation] = useState<Explain | null>(null); const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  useAIPageContext({ page_type: datasetId ? "dataset" : "quality", dataset_id: datasetId });
  const load = useCallback(async (id = assetId) => {
    if (!id) return;
    setLoading(true); setError("");
    const [latest, past, ruleRows, ai] = await Promise.all([
      api<TrustSnapshot & { snapshot?: null }>(`/api/v1/workspaces/${workspaceId}/trust/${id}`),
      api<HistoryResponse>(`/api/v1/workspaces/${workspaceId}/trust/${id}/history?limit=30`),
      api<TrustRule[]>(`/api/v1/workspaces/${workspaceId}/catalog/${id}/quality-rules`),
      api<{ configured?: boolean }>(`/api/v1/workspaces/${workspaceId}/ai/status`),
    ]);
    if (latest.error) setError(latest.error); else setSnapshot(latest.data?.snapshot === null ? null : latest.data ?? null);
    if (past.data) setHistory(past.data.items); if (ruleRows.data) setRules(ruleRows.data); setAiEnabled(Boolean(ai.data?.configured)); setLoading(false);
  }, [assetId, workspaceId]);
  useEffect(() => {
    let active = true;
    if (initialAssetId) return;
    if (!datasetId && !tableId) return;
    api<{ items: Asset[] }>(`/api/v1/workspaces/${workspaceId}/catalog?page=1&page_size=100`).then(result => {
      if (!active) return;
      const match = result.data?.items.find(a => datasetId ? a.dataset_id === datasetId : a.lakehouse_table_id === tableId);
      if (match) setAssetId(match.id); else { setError("This asset has not been registered in the catalog yet."); setLoading(false); }
    });
    return () => { active = false; };
  }, [initialAssetId, datasetId, tableId, workspaceId]);
  useEffect(() => { if (assetId) { void Promise.resolve().then(() => load(assetId)); } }, [assetId, load]);
  async function mutate(path: string, method: string, body?: unknown) {
    setBusy(true); const result = await api(path, { method, body: body === undefined ? undefined : JSON.stringify(body) }); setBusy(false);
    if (result.error) { setError(result.error); return false; } await load(); return true;
  }
  async function recompute() { setBusy(true); const result = await api<TrustSnapshot>(`/api/v1/workspaces/${workspaceId}/trust/${assetId}/compute`, { method: "POST" }); setBusy(false); if (result.error) setError(result.error); else { setSnapshot(result.data ?? null); await load(); } }
  async function explain() { setBusy(true); const result = await api<Explain>(`/api/v1/workspaces/${workspaceId}/trust/${assetId}/explain`, { method: "POST", body: "{}" }); setBusy(false); if (result.error) setError(result.error); else setExplanation(result.data ?? null); }
  const points = history.filter(item => item.overall_score != null).slice().reverse();
  return <section className="space-y-5" aria-label="Trust Passport">
    {error && <p role="alert" className="rounded-lg border border-red-500/40 p-3 text-sm text-red-300">{error}</p>}
    {loading ? <p role="status" className="text-sm text-[var(--muted)]">Loading Trust Passport…</p> : !snapshot ? <div className="rounded-xl border border-[var(--border)] p-5"><p className="text-sm text-[var(--muted)]">No trust snapshot has been computed for this asset.</p>{canEdit && <button type="button" disabled={busy || !assetId} onClick={() => void recompute()} className="mt-3 rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-black">Recompute</button>}</div> : <>
      <div className="flex flex-wrap items-center gap-5 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5"><OverallTrustScore score={snapshot.overall_score} /><div className="min-w-52 flex-1"><h2 className="text-lg font-semibold">Trust Passport</h2><p className="mt-1 text-sm text-[var(--muted)]">Computed {new Date(snapshot.computed_at).toLocaleString()} · {snapshot.sample_rows.toLocaleString()} sampled rows{snapshot.sampled ? " (sampled)" : ""}</p><p className="mt-1 text-xs text-[var(--muted)]">Trigger: {snapshot.trigger}{snapshot.total_rows != null ? ` · ${snapshot.total_rows.toLocaleString()} total rows` : ""}</p><div className="mt-3 flex flex-wrap gap-2">{canEdit && <button type="button" disabled={busy} onClick={() => void recompute()} className="rounded-lg bg-[var(--accent)] px-3 py-2 text-sm font-semibold text-black">{busy ? "Working…" : "Recompute"}</button>}<button type="button" disabled={!aiEnabled || busy} title={!aiEnabled ? "AI is disabled for this workspace" : undefined} onClick={() => void explain()} className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50">Explain with AI</button></div></div></div>
      {explanation && <aside className="rounded-xl border border-[var(--border)] p-4"><p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">AI estimate</p><p className="text-sm">{explanation.summary}</p>{explanation.recommendations.length > 0 && <ul className="mt-2 list-disc pl-5 text-sm">{explanation.recommendations.map((item, i) => <li key={i}>{item}</li>)}</ul>}</aside>}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{Object.entries(snapshot.metrics).filter(([key]) => key !== "_metadata").map(([name, metric]) => <TrustMetricCard key={name} name={name} metric={metric} />)}</div>
      <section className="rounded-xl border border-[var(--border)] p-4"><h3 className="font-semibold">Score history</h3>{points.length < 2 ? <p className="mt-2 text-sm text-[var(--muted)]">More computed snapshots are needed to show a trend.</p> : <svg role="img" aria-label="Trust score history" viewBox="0 0 300 70" className="mt-3 h-20 w-full"><polyline fill="none" stroke="var(--accent)" strokeWidth="3" points={points.map((p, i) => `${i * (290 / (points.length - 1)) + 5},${65 - (p.overall_score ?? 0) * .6}`).join(" ")} /></svg>}</section>
      <section className="rounded-xl border border-[var(--border)] p-4"><h3 className="font-semibold">Rule results</h3>{snapshot.rule_results.length ? <ul className="mt-2 space-y-2 text-sm">{snapshot.rule_results.map((rule, i) => <li key={`${rule.rule_id}-${i}`} className="flex justify-between gap-2 border-b border-[var(--border)] py-2"><span>{rule.rule_type}{rule.column_name ? ` · ${rule.column_name}` : ""} · {rule.severity}</span><span>{rule.status} ({rule.passed}/{rule.checked})</span></li>)}</ul> : <p className="mt-2 text-sm text-[var(--muted)]">No enabled rules were measured.</p>}</section>
      <div className="grid gap-3 md:grid-cols-2"><section className="rounded-xl border border-[var(--border)] p-4"><h3 className="font-semibold">Limitations</h3>{snapshot.limitations.length ? <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-[var(--muted)]">{snapshot.limitations.map((item, i) => <li key={i}>{item}</li>)}</ul> : <p className="mt-2 text-sm text-[var(--muted)]">No known limitations.</p>}</section><section className="rounded-xl border border-[var(--border)] p-4"><h3 className="font-semibold">Last successful validation</h3><p className="mt-2 text-sm text-[var(--muted)]">{snapshot.last_successful_validation ? new Date(snapshot.last_successful_validation).toLocaleString() : "Not measured"}</p></section></div>
      <TrustRuleEditor rules={rules} canEdit={canEdit} freshness={typeof snapshot.metrics.freshness?.value === "object" && snapshot.metrics.freshness.value !== null && "target_hours" in snapshot.metrics.freshness.value ? Number((snapshot.metrics.freshness.value as {target_hours:number}).target_hours) : freshness} onSave={(rule, id) => mutate(`/api/v1/workspaces/${workspaceId}/catalog/${assetId}/quality-rules${id ? `/${id}` : ""}`, id ? "PATCH" : "POST", rule).then(() => undefined)} onToggle={rule => mutate(`/api/v1/workspaces/${workspaceId}/catalog/${assetId}/quality-rules/${rule.id}`, "PATCH", { enabled: !rule.enabled }).then(() => undefined)} onDelete={rule => mutate(`/api/v1/workspaces/${workspaceId}/catalog/${assetId}/quality-rules/${rule.id}`, "DELETE").then(() => undefined)} onFreshness={hours => mutate(`/api/v1/workspaces/${workspaceId}/catalog/${assetId}/freshness`, "PATCH", { freshness_target_hours: hours }).then(() => setFreshness(hours))} />
    </>}
  </section>;
}
