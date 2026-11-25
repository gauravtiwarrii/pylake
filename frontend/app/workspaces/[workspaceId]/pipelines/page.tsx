"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";

type Step = { id: string; step_key: string; name: string; step_type: string; execution_order: number; configuration_json: Record<string, unknown>; dependencies_json: string[] };
type Pipeline = { id: string; name: string; description: string | null; status: "DRAFT" | "ACTIVE" | "DISABLED"; created_at: string };
type Run = { id: string; status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED"; created_at: string; started_at: string | null; completed_at: string | null; duration_ms: number | null; error_message: string | null };
type StepRun = { id: string; status: string; duration_ms: number | null; rows_processed: number | null; output_metadata_json: Record<string, unknown>; error_message: string | null };

export default function PipelinesPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const { user } = useAuth();
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [selected, setSelected] = useState<Pipeline | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [activeRun, setActiveRun] = useState<Run | null>(null);
  const [stepRuns, setStepRuns] = useState<StepRun[]>([]);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [metrics, setMetrics] = useState<Record<string, unknown> | null>(null);
  const [stepType, setStepType] = useState<"SOURCE_DATASET" | "TRANSFORM" | "DATA_QUALITY" | "SQL_QUERY" | "MATERIALIZE">("SOURCE_DATASET");
  const [stepName, setStepName] = useState("");
  const [stepConfig, setStepConfig] = useState("{}");

  const addStep = async () => {
    if (!selected || !stepName.trim()) return;
    let configuration: Record<string, unknown>;
    try {
      configuration = JSON.parse(stepConfig);
    } catch {
      setError("Step configuration must be valid JSON");
      return;
    }
    const nextStep = {
      step_key: `step_${steps.length + 1}`,
      name: stepName.trim(),
      step_type: stepType,
      configuration,
      dependencies: steps.length ? [steps[steps.length - 1].step_key] : [],
      execution_order: steps.length + 1,
    };
    const existing = steps.map((step) => ({
      step_key: step.step_key,
      name: step.name,
      step_type: step.step_type,
      configuration: step.configuration_json,
      dependencies: step.dependencies_json,
      execution_order: step.execution_order,
    }));
    const response = await api<Pipeline>(`/api/v1/workspaces/${workspaceId}/pipelines/${selected.id}`, {
      method: "PATCH",
      body: JSON.stringify({ steps: [...existing, nextStep] }),
    });
    if (response.error) setError(response.error);
    else {
      setStepName("");
      setStepConfig("{}");
      await selectPipeline(selected);
    }
  };

  const load = useCallback(async () => {
    const [response, metricsResponse] = await Promise.all([
      api<Pipeline[]>(`/api/v1/workspaces/${workspaceId}/pipelines`),
      api<Record<string, unknown>>(`/api/v1/workspaces/${workspaceId}/pipelines/metrics`),
    ]);
    if (response.error) setError(response.error);
    else setPipelines(response.data ?? []);
    if (!metricsResponse.error) setMetrics(metricsResponse.data ?? null);
  }, [workspaceId]);

  useEffect(() => {
    if (!user) return;
    const timeout = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timeout);
  }, [load, user]);

  const selectPipeline = async (pipeline: Pipeline) => {
    setSelected(pipeline);
    setError("");
    const [detail, runList] = await Promise.all([
      api<{ pipeline: Pipeline; steps: Step[] }>(`/api/v1/workspaces/${workspaceId}/pipelines/${pipeline.id}`),
      api<Run[]>(`/api/v1/workspaces/${workspaceId}/pipelines/${pipeline.id}/runs`),
    ]);
    if (detail.error) setError(detail.error);
    else setSteps(detail.data?.steps ?? []);
    if (!runList.error) setRuns(runList.data ?? []);
  };

  const createPipeline = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    const response = await api<Pipeline>(`/api/v1/workspaces/${workspaceId}/pipelines`, {
      method: "POST",
      body: JSON.stringify({ name, description: description || null, status: "DRAFT", steps: [] }),
    });
    if (response.error) setError(response.error);
    else {
      setCreateOpen(false);
      setName("");
      setDescription("");
      await load();
    }
  };

  const runPipeline = async () => {
    if (!selected) return;
    setError("");
    const response = await api<Run>(`/api/v1/workspaces/${workspaceId}/pipelines/${selected.id}/runs`, { method: "POST" });
    if (response.error) setError(response.error);
    else await selectPipeline(selected);
  };

  const viewRun = async (run: Run) => {
    setActiveRun(run);
    const response = await api<{ run: Run; steps: StepRun[] }>(`/api/v1/workspaces/${workspaceId}/pipelines/runs/${run.id}/logs`);
    if (response.error) setError(response.error);
    else {
      setActiveRun(response.data?.run ?? run);
      setStepRuns(response.data?.steps ?? []);
    }
  };

  return (
    <main className="min-h-screen px-6 py-8 md:px-10">
      <div className="mx-auto max-w-7xl">
        <Link href={`/workspaces/${workspaceId}`} className="text-sm text-[#98a0b3]">Back to workspace</Link>
        <div className="mt-2 flex items-center justify-between">
          <h1 className="text-3xl font-semibold">Pipelines</h1>
          <button onClick={() => setCreateOpen(true)} className="h-10 rounded-md bg-[#7dd3fc] px-4 text-sm font-medium text-[#071018]">Create pipeline</button>
        </div>
        {error && <div className="mt-5 rounded-md border border-red-900 bg-red-950/40 px-4 py-3 text-sm text-red-300">{error}</div>}

        {metrics && (
          <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-5">
            {([
              ["Total runs", metrics.total_runs],
              ["Succeeded", (metrics.status_distribution as Record<string, number>)?.SUCCEEDED ?? 0],
              ["Failed", (metrics.status_distribution as Record<string, number>)?.FAILED ?? 0],
              ["Running", (metrics.status_distribution as Record<string, number>)?.RUNNING ?? 0],
              ["Average ms", metrics.average_duration_ms],
            ] as [string, unknown][]).map(([label, value]) => (
              <div key={String(label)} className="rounded-md border border-[#242936] bg-[#11141b] p-3">
                <p className="text-xs text-[#98a0b3]">{label}</p>
                <p className="mt-1 font-medium">{String(value ?? 0)}</p>
              </div>
            ))}
          </div>
        )}

        <div className="mt-6 grid gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
          <section className="space-y-3">
            {pipelines.length === 0 ? (
              <div className="rounded-lg border border-dashed border-[#303646] p-6 text-sm text-[#98a0b3]">No pipelines created.</div>
            ) : pipelines.map((pipeline) => (
              <button key={pipeline.id} onClick={() => void selectPipeline(pipeline)} className={`w-full rounded-lg border p-4 text-left ${selected?.id === pipeline.id ? "border-[#7dd3fc] bg-[#11141b]" : "border-[#242936] bg-[#0d1016]"}`}>
                <p className="font-medium">{pipeline.name}</p>
                <p className="mt-1 text-xs text-[#98a0b3]">{pipeline.status}</p>
                {pipeline.description && <p className="mt-3 text-sm text-[#98a0b3]">{pipeline.description}</p>}
              </button>
            ))}
          </section>

          <section className="rounded-lg border border-[#242936] bg-[#11141b] p-5">
            {!selected ? (
              <p className="text-sm text-[#98a0b3]">Select a pipeline to view steps and runs.</p>
            ) : (
              <>
                <div className="flex items-start justify-between">
                  <div><h2 className="font-medium">{selected.name}</h2><p className="mt-1 text-sm text-[#98a0b3]">{selected.status}</p></div>
                  <button onClick={runPipeline} className="h-9 rounded-md bg-[#7dd3fc] px-4 text-sm font-medium text-[#071018]">Run pipeline</button>
                </div>
                <h3 className="mt-6 font-medium">Steps</h3>
                <div className="mt-3 grid gap-2 md:grid-cols-[1fr_180px_1fr_auto]">
                  <input value={stepName} onChange={(event) => setStepName(event.target.value)} placeholder="Step name" className="h-9 rounded-md border border-[#303646] bg-[#0b0d12] px-3 text-sm" />
                  <select value={stepType} onChange={(event) => setStepType(event.target.value as typeof stepType)} className="h-9 rounded-md border border-[#303646] bg-[#0b0d12] px-2 text-sm">
                    <option value="SOURCE_DATASET">Source dataset</option>
                    <option value="TRANSFORM">Transform</option>
                    <option value="DATA_QUALITY">Data quality</option>
                    <option value="SQL_QUERY">SQL query</option>
                    <option value="MATERIALIZE">Materialize</option>
                  </select>
                  <input value={stepConfig} onChange={(event) => setStepConfig(event.target.value)} placeholder='{"table_name":"customers"}' className="h-9 rounded-md border border-[#303646] bg-[#0b0d12] px-3 font-mono text-xs" />
                  <button onClick={addStep} className="h-9 rounded-md border border-[#303646] px-3 text-sm">Add step</button>
                </div>
                {steps.length === 0 ? <p className="mt-3 text-sm text-[#98a0b3]">No configured steps.</p> : (
                  <div className="mt-3 space-y-2">{steps.map((step) => (
                    <div key={step.id} className="rounded-md border border-[#242936] p-3">
                      <p className="text-sm font-medium">{step.execution_order}. {step.name}</p>
                      <p className="mt-1 text-xs text-[#98a0b3]">{step.step_type} · dependencies: {step.dependencies_json.join(", ") || "none"}</p>
                    </div>
                  ))}</div>
                )}
                <h3 className="mt-6 font-medium">Runs</h3>
                <div className="mt-3 divide-y divide-[#242936]">{runs.map((run) => (
                  <button key={run.id} onClick={() => void viewRun(run)} className="w-full py-3 text-left">
                    <div className="flex justify-between text-sm"><span>{run.status}</span><span className="text-[#98a0b3]">{run.duration_ms ?? 0} ms</span></div>
                    {run.error_message && <p className="mt-1 text-xs text-red-300">{run.error_message}</p>}
                  </button>
                ))}</div>
                {activeRun && (
                  <div className="mt-5 rounded-md border border-[#303646] p-4">
                    <h3 className="font-medium">Run logs</h3>
                    <div className="mt-3 space-y-2">{stepRuns.map((stepRun) => (
                      <div key={stepRun.id} className="text-sm"><span>{stepRun.status}</span>{stepRun.error_message && <span className="ml-2 text-red-300">{stepRun.error_message}</span>}</div>
                    ))}</div>
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      </div>

      {createOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 px-6">
          <form onSubmit={createPipeline} className="w-full max-w-lg rounded-xl border border-[#303646] bg-[#11141b] p-6">
            <h2 className="text-lg font-semibold">Create pipeline</h2>
            <label className="mt-5 block text-sm">Name
              <input required value={name} onChange={(event) => setName(event.target.value)} className="mt-2 h-10 w-full rounded-md border border-[#303646] bg-[#0b0d12] px-3" />
            </label>
            <label className="mt-4 block text-sm">Description
              <textarea value={description} onChange={(event) => setDescription(event.target.value)} className="mt-2 h-24 w-full rounded-md border border-[#303646] bg-[#0b0d12] p-3" />
            </label>
            <div className="mt-5 flex justify-end gap-3">
              <button type="button" onClick={() => setCreateOpen(false)} className="h-10 px-4 text-sm text-[#98a0b3]">Cancel</button>
              <button className="h-10 rounded-md bg-[#7dd3fc] px-4 text-sm font-medium text-[#071018]">Create</button>
            </div>
          </form>
        </div>
      )}
    </main>
  );
}
