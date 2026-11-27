"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useMemo, useState } from "react";
import { Bot, Check, CircleAlert, FileText, Play, Plus, RefreshCw, ShieldCheck, X } from "lucide-react";
import { useAIPageContext } from "@/components/ai-page-context";
import { useAuth } from "@/components/auth-provider";
import { ApproveButton } from "@/components/autopilot/ApprovalControls";
import { PlanStepCard } from "@/components/autopilot/PlanStepCard";
import { ProposedActionCard } from "@/components/autopilot/ProposedActionCard";
import type { AutopilotPlan, PlanStep, Recommendation } from "@/components/autopilot/types";
import { api } from "@/lib/api";

type Dataset = {
  id: string;
  name: string;
  ingestion_status: string;
  row_count: number | null;
};

type AIStatus = { configured: boolean; provider: string; model: string };
type PlanListItem = Pick<AutopilotPlan, "id" | "goal" | "status" | "created_at">;
type PlanReport = {
  plan_id: string;
  status: string;
  goal: string;
  steps: { step_order: number; action_key: string; title: string; status: string; duration_ms: number | null; error_message: string | null; result: Record<string, unknown> | null }[];
  created: Record<string, string[]>;
  not_done: { step_order: number; action_key: string; status: string; reason: string }[];
  error_message: string | null;
};

const actionLabels: Record<string, string> = {
  profile_dataset: "Profile dataset",
  promote_table: "Promote table",
  apply_transformation: "Apply transformation",
  run_readonly_sql: "Run read-only SQL",
  create_pipeline: "Create pipeline",
  create_schedule: "Create schedule",
  compute_trust: "Compute Trust Passport",
};

const actionTemplate = (action: string, datasetId: string): Record<string, unknown> => {
  switch (action) {
    case "profile_dataset": return { dataset_id: datasetId || "" };
    case "promote_table": return { table_id: "", target_layer: "SILVER", partition_columns: [] };
    case "apply_transformation": return { table_id: "", transformation_type: "deduplicate", configuration: {}, target_layer: "SILVER" };
    case "run_readonly_sql": return { sql: "SELECT * FROM customers LIMIT 100", limit: 100 };
    case "create_pipeline": return { name: "New pipeline", description: null, steps: [] };
    case "create_schedule": return { pipeline_id: "", cron_expression: "0 9 * * *", timezone: "UTC", enabled: true };
    case "compute_trust": return { asset_id: "" };
    default: return {};
  }
};

const sleep = (milliseconds: number) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

function StatusPill({ status }: { status: string }) {
  const tone = status === "SUCCEEDED" || status === "APPROVED" ? "text-emerald-300 border-emerald-500/30 bg-emerald-500/10"
    : status === "FAILED" ? "text-rose-300 border-rose-500/30 bg-rose-500/10"
      : status === "RUNNING" ? "text-sky-300 border-sky-500/30 bg-sky-500/10"
        : "text-[var(--muted)] border-[var(--border)] bg-[var(--surface-raised)]";
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-[10px] font-semibold ${tone}`}>{status}</span>;
}

export default function AutopilotPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const { user } = useAuth();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [aiStatus, setAIStatus] = useState<AIStatus | null>(null);
  const [plans, setPlans] = useState<PlanListItem[]>([]);
  const [plan, setPlan] = useState<AutopilotPlan | null>(null);
  const [report, setReport] = useState<PlanReport | null>(null);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [recommendationsLoading, setRecommendationsLoading] = useState(false);
  const [goal, setGoal] = useState("");
  const [manualOpen, setManualOpen] = useState(false);
  const [manualAction, setManualAction] = useState("profile_dataset");
  const [manualArguments, setManualArguments] = useState("{}");
  const [manualSteps, setManualSteps] = useState<{ action_key: string; title: string; arguments: Record<string, unknown> }[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useAIPageContext({ page_type: "autopilot", active_view: plan?.status.toLowerCase() ?? "planner", dataset_id: datasetId || undefined });

  const loadPlans = useCallback(async () => {
    const response = await api<PlanListItem[]>(`/api/v1/workspaces/${workspaceId}/ai/autopilot/plans`);
    if (response.error) setError(response.error);
    else setPlans(response.data ?? []);
  }, [workspaceId]);

  const loadPlan = useCallback(async (planId: string) => {
    const response = await api<AutopilotPlan>(`/api/v1/workspaces/${workspaceId}/ai/autopilot/plans/${planId}`);
    if (response.error) setError(response.error);
    else if (response.data) setPlan(response.data);
    return response.data;
  }, [workspaceId]);

  const loadRecommendations = useCallback(async (selectedDatasetId: string) => {
    if (!selectedDatasetId) {
      setRecommendations([]);
      return;
    }
    setRecommendationsLoading(true);
    const query = new URLSearchParams({ page_type: "dataset", dataset_id: selectedDatasetId });
    const response = await api<Recommendation[]>(`/api/v1/workspaces/${workspaceId}/ai/recommendations?${query.toString()}`);
    if (response.error) setError(response.error);
    else setRecommendations(response.data ?? []);
    setRecommendationsLoading(false);
  }, [workspaceId]);

  useEffect(() => {
    if (!user) return;
    let active = true;
    const load = async () => {
      setLoading(true);
      const [datasetResult, statusResult, planResult] = await Promise.all([
        api<{ items: Dataset[]; total: number }>(`/api/v1/workspaces/${workspaceId}/datasets?page=1&page_size=100`),
        api<AIStatus>(`/api/v1/workspaces/${workspaceId}/ai/status`),
        api<PlanListItem[]>(`/api/v1/workspaces/${workspaceId}/ai/autopilot/plans`),
      ]);
      if (!active) return;
      if (datasetResult.error) setError(datasetResult.error);
      else {
        const availableDatasets = datasetResult.data?.items ?? [];
        setDatasets(availableDatasets);
        const firstReady = availableDatasets.find((item) => item.ingestion_status === "COMPLETED");
        if (firstReady) setDatasetId((current) => current || firstReady.id);
      }
      if (statusResult.error) setError(statusResult.error);
      else setAIStatus(statusResult.data ?? null);
      if (planResult.error) setError(planResult.error);
      else setPlans(planResult.data ?? []);
      setLoading(false);
    };
    void load();
    return () => { active = false; };
  }, [user, workspaceId]);

  useEffect(() => {
    if (!datasetId || !user) return;
    const timeout = window.setTimeout(() => void loadRecommendations(datasetId), 0);
    return () => window.clearTimeout(timeout);
  }, [datasetId, loadRecommendations, user]);

  const selectedDataset = useMemo(() => datasets.find((item) => item.id === datasetId), [datasets, datasetId]);

  const makePlan = async (steps?: { action_key: string; title: string; arguments: Record<string, unknown> }[]) => {
    setError("");
    setBusy("create");
    const body = steps
      ? { goal: goal.trim(), steps }
      : { goal: goal.trim(), ...(datasetId ? { dataset_id: datasetId } : {}) };
    const response = await api<AutopilotPlan>(`/api/v1/workspaces/${workspaceId}/ai/autopilot/plans`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (response.error) setError(response.error);
    else if (response.data) {
      setPlan(response.data);
      setReport(null);
      setManualSteps([]);
      setManualOpen(false);
      await loadPlans();
    }
    setBusy("");
  };

  const addManualStep = () => {
    setError("");
    let parsed: unknown;
    try {
      parsed = JSON.parse(manualArguments);
    } catch {
      setError("Step arguments must be valid JSON.");
      return;
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      setError("Step arguments must be a JSON object.");
      return;
    }
    setManualSteps((current) => [...current, {
      action_key: manualAction,
      title: actionLabels[manualAction],
      arguments: parsed as Record<string, unknown>,
    }]);
    setManualArguments(JSON.stringify(actionTemplate(manualAction, datasetId), null, 2));
  };

  const preview = async () => {
    if (!plan) return;
    setBusy("preview");
    setError("");
    const response = await api<AutopilotPlan>(`/api/v1/workspaces/${workspaceId}/ai/autopilot/plans/${plan.id}/preview`, { method: "POST" });
    if (response.error) setError(response.error);
    else if (response.data) { setPlan(response.data); setReport(null); }
    setBusy("");
  };

  const approve = async () => {
    if (!plan?.plan_hash || plan.status !== "PREVIEWED") return;
    setBusy("approve");
    setError("");
    const response = await api<AutopilotPlan>(`/api/v1/workspaces/${workspaceId}/ai/autopilot/plans/${plan.id}/approve`, {
      method: "POST",
      body: JSON.stringify({ plan_hash: plan.plan_hash }),
    });
    if (response.error) setError(response.error);
    else if (response.data) { setPlan(response.data); await loadPlans(); }
    setBusy("");
  };

  const execute = async () => {
    if (!plan || plan.status !== "APPROVED") return;
    const planId = plan.id;
    setError("");
    setBusy("execute");
    let finished = false;
    const request = api<AutopilotPlan>(`/api/v1/workspaces/${workspaceId}/ai/autopilot/plans/${planId}/execute`, { method: "POST" })
      .then((response) => { finished = true; return response; });
    while (!finished) {
      await sleep(900);
      if (!finished) await loadPlan(planId);
    }
    const response = await request;
    if (response.error) setError(response.error);
    else if (response.data) {
      setPlan(response.data);
      const reportResponse = await api<PlanReport>(`/api/v1/workspaces/${workspaceId}/ai/autopilot/plans/${planId}/report`);
      if (reportResponse.data) setReport(reportResponse.data);
      if (reportResponse.error) setError(reportResponse.error);
      await loadPlans();
    }
    setBusy("");
  };

  const cancel = async () => {
    if (!plan) return;
    setBusy("cancel");
    setError("");
    const response = await api<AutopilotPlan>(`/api/v1/workspaces/${workspaceId}/ai/autopilot/plans/${plan.id}/cancel`, { method: "POST" });
    if (response.error) setError(response.error);
    else if (response.data) { setPlan(response.data); await loadPlans(); }
    setBusy("");
  };

  const showReport = async () => {
    if (!plan) return;
    setBusy("report");
    const response = await api<PlanReport>(`/api/v1/workspaces/${workspaceId}/ai/autopilot/plans/${plan.id}/report`);
    if (response.error) setError(response.error);
    else setReport(response.data ?? null);
    setBusy("");
  };

  const choosePlan = async (planId: string) => {
    setReport(null);
    await loadPlan(planId);
  };

  const decideRecommendation = async (recommendation: Recommendation, decision: "accept" | "dismiss") => {
    setBusy(recommendation.id);
    setError("");
    const response = await api<{ plan_id?: string } | Recommendation>(
      `/api/v1/workspaces/${workspaceId}/ai/recommendations/${recommendation.id}/${decision}`,
      { method: "POST" },
    );
    if (response.error) setError(response.error);
    else {
      if (decision === "accept" && response.data && "plan_id" in response.data && response.data.plan_id) {
        await loadPlan(response.data.plan_id);
        await loadPlans();
        setReport(null);
      }
      setRecommendations((current) => current.filter((item) => item.id !== recommendation.id));
    }
    setBusy("");
  };

  const canCancel = plan && ["DRAFT", "PREVIEWED", "APPROVED", "RUNNING"].includes(plan.status);
  const terminal = plan && ["SUCCEEDED", "FAILED", "CANCELLED"].includes(plan.status);

  return (
    <main className="min-h-[calc(100vh-64px)] px-4 py-6 md:px-7 lg:px-8">
      <div className="mx-auto max-w-[1500px]">
        <Link href={`/workspaces/${workspaceId}`} className="text-xs text-[var(--muted)] hover:text-[var(--accent)]">Workspace / Overview</Link>
        <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.16em] text-[var(--accent)]"><Bot size={14} /> Governed automation</p>
            <h1 className="mt-1 text-3xl font-semibold tracking-tight">Autopilot</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--muted)]">Build a workspace plan, inspect a no-write preview, then explicitly approve it before execution.</p>
          </div>
          <button type="button" onClick={() => { void loadPlans(); if (datasetId) void loadRecommendations(datasetId); }} className="inline-flex h-9 items-center gap-2 rounded-lg border border-[var(--border-strong)] px-3 text-xs font-medium hover:bg-[var(--surface-hover)]">
            <RefreshCw size={14} /> Refresh
          </button>
        </div>

        {error && <div role="alert" className="mt-5 rounded-lg border border-[color-mix(in_srgb,var(--danger)_35%,transparent)] bg-[color-mix(in_srgb,var(--danger)_8%,var(--surface))] px-4 py-3 text-sm text-[var(--danger)]">{error}</div>}
        {loading ? <p role="status" className="mt-8 text-sm text-[var(--muted)]">Loading Autopilot…</p> : (
          <div className="mt-6 grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
            <div className="min-w-0 space-y-6">
              <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 shadow-[var(--shadow-soft)]">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="text-lg font-semibold">Create a plan</h2>
                    <p className="mt-1 text-xs text-[var(--muted)]">Plans are scoped to this workspace and limited to allowlisted actions.</p>
                  </div>
                  {aiStatus && <span className={`rounded-full border px-2.5 py-1 text-[10px] font-medium ${aiStatus.configured ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" : "border-[var(--border)] text-[var(--muted)]"}`}>{aiStatus.configured ? `AI ready · ${aiStatus.provider}` : "AI disabled"}</span>}
                </div>

                {!aiStatus?.configured && (
                  <div className="mt-4 flex gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-100" role="status">
                    <CircleAlert size={17} className="mt-0.5 shrink-0" />
                    <p>AI planning is disabled for this workspace. You can still build a plan manually by choosing an allowed action and entering its JSON arguments.</p>
                  </div>
                )}

                <label htmlFor="autopilot-goal" className="mt-5 block text-xs font-medium">Plan goal</label>
                <textarea id="autopilot-goal" value={goal} onChange={(event) => setGoal(event.target.value)} maxLength={4000} rows={3} placeholder="What should Autopilot prepare?" className="mt-2 w-full resize-y rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-3 py-2.5 text-sm outline-none focus:border-[var(--accent)]" />
                <div className="mt-4 grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
                  <div>
                    <label htmlFor="autopilot-dataset" className="block text-xs font-medium">Dataset context <span className="font-normal text-[var(--muted)]">(optional)</span></label>
                    <select id="autopilot-dataset" value={datasetId} onChange={(event) => setDatasetId(event.target.value)} className="mt-2 h-10 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-3 text-sm outline-none focus:border-[var(--accent)]">
                      <option value="">No dataset selected</option>
                      {datasets.map((dataset) => <option key={dataset.id} value={dataset.id} disabled={dataset.ingestion_status !== "COMPLETED"}>{dataset.name} · {dataset.ingestion_status}</option>)}
                    </select>
                  </div>
                  {aiStatus?.configured && (
                    <button type="button" onClick={() => void makePlan()} disabled={!goal.trim() || Boolean(busy)} className="h-10 rounded-lg bg-[var(--accent)] px-4 text-sm font-semibold text-[var(--accent-foreground)] hover:bg-[var(--accent-strong)] disabled:cursor-not-allowed disabled:opacity-45">
                      {busy === "create" ? "Generating…" : "Generate plan"}
                    </button>
                  )}
                </div>

                {aiStatus?.configured && <button type="button" onClick={() => setManualOpen((value) => !value)} className="mt-4 text-xs font-medium text-[var(--accent)] hover:underline">{manualOpen ? "Hide manual builder" : "Build a plan manually"}</button>}
                {(manualOpen || !aiStatus?.configured) && (
                  <div className="mt-4 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-4">
                    <h3 className="text-sm font-semibold">Manual step builder</h3>
                    <p className="mt-1 text-xs leading-5 text-[var(--muted)]">Arguments are checked as a JSON object here and validated against workspace data by the server when the plan is created.</p>
                    <div className="mt-4 grid gap-3 md:grid-cols-[220px_minmax(0,1fr)]">
                      <div>
                        <label htmlFor="manual-action" className="block text-xs font-medium">Allowed action</label>
                        <select id="manual-action" value={manualAction} onChange={(event) => { const value = event.target.value; setManualAction(value); setManualArguments(JSON.stringify(actionTemplate(value, datasetId), null, 2)); }} className="mt-2 h-10 w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-2 text-sm">
                          {Object.entries(actionLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                        </select>
                        {manualAction === "profile_dataset" && (
                          <button type="button" onClick={() => setManualArguments(JSON.stringify(actionTemplate(manualAction, datasetId), null, 2))} disabled={!datasetId} className="mt-2 text-left text-[11px] text-[var(--accent)] disabled:opacity-50">Use selected dataset ID</button>
                        )}
                      </div>
                      <div>
                        <label htmlFor="manual-arguments" className="block text-xs font-medium">Arguments JSON</label>
                        <textarea id="manual-arguments" value={manualArguments} onChange={(event) => setManualArguments(event.target.value)} rows={6} spellCheck={false} className="mt-2 w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 font-mono text-xs leading-5 outline-none focus:border-[var(--accent)]" />
                      </div>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <button type="button" onClick={addManualStep} disabled={manualSteps.length >= 20} className="inline-flex h-9 items-center gap-2 rounded-lg border border-[var(--border-strong)] px-3 text-xs font-medium hover:bg-[var(--surface-hover)] disabled:opacity-50"><Plus size={14} /> Add step</button>
                      <span className="text-[11px] text-[var(--muted)]">{manualSteps.length}/20 steps</span>
                    </div>
                    {manualSteps.length > 0 && (
                      <ol className="mt-3 space-y-2">
                        {manualSteps.map((step, index) => (
                          <li key={`${step.action_key}-${index}`} className="flex items-start justify-between gap-3 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3 text-xs">
                            <span><strong>{index + 1}. {step.title}</strong><code className="ml-2 text-[var(--muted)]">{step.action_key}</code><pre className="mt-2 overflow-x-auto font-mono text-[10px] text-[var(--muted)]">{JSON.stringify(step.arguments, null, 2)}</pre></span>
                            <button type="button" onClick={() => setManualSteps((current) => current.filter((_, stepIndex) => stepIndex !== index))} aria-label={`Remove step ${index + 1}`} className="rounded p-1 text-[var(--muted)] hover:text-[var(--danger)]"><X size={15} /></button>
                          </li>
                        ))}
                      </ol>
                    )}
                    <button type="button" onClick={() => void makePlan(manualSteps)} disabled={!goal.trim() || manualSteps.length === 0 || Boolean(busy)} className="mt-4 h-10 rounded-lg bg-[var(--accent)] px-4 text-sm font-semibold text-[var(--accent-foreground)] hover:bg-[var(--accent-strong)] disabled:cursor-not-allowed disabled:opacity-45">
                      {busy === "create" ? "Creating…" : "Create manual plan"}
                    </button>
                  </div>
                )}
              </section>

              {plan ? (
                <section aria-label="Selected Autopilot plan" className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 shadow-[var(--shadow-soft)]">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0"><p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--accent)]">Plan {plan.id.slice(0, 8)}</p><h2 className="mt-1 text-lg font-semibold">{plan.goal}</h2><p className="mt-1 text-xs text-[var(--muted)]">{plan.steps.length} steps{plan.ai_provider ? ` · generated by ${plan.ai_provider}${plan.ai_model ? ` / ${plan.ai_model}` : ""}` : " · manual"}</p></div>
                    <StatusPill status={plan.status} />
                  </div>
                  <div className="flex flex-wrap gap-2 border-y border-[var(--border)] py-4">
                    <button type="button" onClick={() => void preview()} disabled={!(["DRAFT", "PREVIEWED"].includes(plan.status)) || Boolean(busy)} className="h-10 rounded-lg border border-[var(--border-strong)] px-4 text-sm font-medium hover:bg-[var(--surface-hover)] disabled:cursor-not-allowed disabled:opacity-45">{busy === "preview" ? "Previewing…" : "Preview plan"}</button>
                    <ApproveButton plan={plan} busy={busy === "approve"} onApprove={() => void approve()} />
                    <button type="button" onClick={() => void execute()} disabled={plan.status !== "APPROVED" || Boolean(busy)} className="inline-flex h-10 items-center gap-2 rounded-lg bg-[var(--accent)] px-4 text-sm font-semibold text-[var(--accent-foreground)] hover:bg-[var(--accent-strong)] disabled:cursor-not-allowed disabled:opacity-45"><Play size={14} />{busy === "execute" ? "Executing…" : "Execute approved plan"}</button>
                    {canCancel && <button type="button" onClick={() => void cancel()} disabled={Boolean(busy) && busy !== "execute"} className="h-10 rounded-lg border border-[var(--border)] px-4 text-sm text-[var(--muted)] hover:border-[var(--danger)] hover:text-[var(--danger)] disabled:opacity-45">{busy === "cancel" ? "Cancelling…" : plan.status === "RUNNING" ? "Cancel run" : "Cancel"}</button>}
                    {terminal && <button type="button" onClick={() => void showReport()} disabled={Boolean(busy)} className="inline-flex h-10 items-center gap-2 rounded-lg border border-[var(--border)] px-4 text-sm hover:bg-[var(--surface-hover)]"><FileText size={14} />{busy === "report" ? "Loading…" : "View report"}</button>}
                  </div>
                  {plan.plan_hash && <p className="flex items-center gap-2 break-all text-[10px] text-[var(--muted)]"><ShieldCheck size={13} className="shrink-0 text-emerald-400" /> Approval binds to plan hash <code>{plan.plan_hash}</code></p>}
                  {plan.steps.length ? <div className="space-y-3">{plan.steps.map((step: PlanStep) => <PlanStepCard key={step.id} step={step} />)}</div> : <p className="text-sm text-[var(--muted)]">This plan has no steps.</p>}
                  {report && (
                    <section aria-label="Execution report" className="rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-4">
                      <h3 className="font-semibold">Execution report · {report.status}</h3>
                      {report.error_message && <p className="mt-2 text-sm text-[var(--danger)]">{report.error_message}</p>}
                      <div className="mt-4 grid gap-4 md:grid-cols-2">
                        <div><h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">Created resources</h4><ul className="mt-2 space-y-1 text-xs">{Object.entries(report.created ?? {}).flatMap(([kind, ids]) => ids.map((id) => <li key={`${kind}-${id}`}><span className="text-[var(--muted)]">{kind.replaceAll("_", " ")}: </span><code>{id}</code></li>))}</ul></div>
                        <div><h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">Step outcomes</h4><ul className="mt-2 space-y-2">{report.steps.map((item) => <li key={item.step_order} className="text-xs"><div className="flex flex-wrap justify-between gap-2"><span>{item.step_order}. {item.title}</span><span>{item.status} · {item.duration_ms ?? 0} ms</span></div>{item.error_message && <p className="mt-1 text-[var(--danger)]">{item.error_message}</p>}</li>)}</ul></div>
                      </div>
                      {report.not_done.length > 0 && <p className="mt-4 text-xs text-[var(--muted)]">Skipped or incomplete: {report.not_done.map((item) => `${item.step_order}. ${item.reason}`).join(" · ")}</p>}
                    </section>
                  )}
                </section>
              ) : <div className="rounded-xl border border-dashed border-[var(--border-strong)] p-8 text-center text-sm text-[var(--muted)]">Create a plan or select one from your past plans to review its steps.</div>}
            </div>

            <aside className="space-y-6">
              <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-[var(--shadow-soft)]">
                <div className="flex items-center justify-between gap-2"><h2 className="font-semibold">Past plans</h2><span className="text-[10px] text-[var(--muted)]">{plans.length}</span></div>
                {plans.length === 0 ? <p className="mt-4 text-xs text-[var(--muted)]">No plans in this workspace yet.</p> : (
                  <ul className="mt-3 max-h-80 space-y-1 overflow-y-auto">
                    {plans.map((item) => <li key={item.id}><button type="button" onClick={() => void choosePlan(item.id)} aria-current={plan?.id === item.id ? "true" : undefined} className={`w-full rounded-lg border px-3 py-2 text-left ${plan?.id === item.id ? "border-[var(--accent)] bg-[var(--accent-soft)]" : "border-transparent hover:bg-[var(--surface-hover)]"}`}><span className="block truncate text-xs font-medium">{item.goal}</span><span className="mt-1 flex items-center justify-between gap-2 text-[10px] text-[var(--muted)]"><time>{new Date(item.created_at).toLocaleDateString()}</time><StatusPill status={item.status} /></span></button></li>)}
                  </ul>
                )}
              </section>

              <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-[var(--shadow-soft)]">
                <div className="flex items-center justify-between gap-2"><h2 className="font-semibold">Recommendations</h2>{datasetId && <span className="text-[10px] text-[var(--muted)]">{selectedDataset?.name ?? "Dataset"}</span>}</div>
                {!datasetId ? <p className="mt-3 text-xs leading-5 text-[var(--muted)]">Select a dataset above to see evidence-based suggestions.</p> : recommendationsLoading ? <p role="status" className="mt-3 text-xs text-[var(--muted)]">Checking dataset recommendations…</p> : recommendations.length === 0 ? <p className="mt-3 text-xs leading-5 text-[var(--muted)]">No open recommendations for this dataset.</p> : (
                  <div className="mt-3 space-y-3">{recommendations.map((recommendation) => <ProposedActionCard key={recommendation.id} recommendation={recommendation} busy={busy === recommendation.id} onAccept={() => void decideRecommendation(recommendation, "accept")} onDismiss={() => void decideRecommendation(recommendation, "dismiss")} />)}</div>
                )}
                <p className="mt-3 flex items-start gap-2 text-[10px] leading-4 text-[var(--muted)]"><Check size={12} className="mt-0.5 shrink-0" /> Accepting creates a draft plan; it does not approve or execute the action.</p>
              </section>
            </aside>
          </div>
        )}
      </div>
    </main>
  );
}
