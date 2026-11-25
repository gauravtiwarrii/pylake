"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import {
  Activity,
  ArrowRight,
  Braces,
  Database,
  FolderKanban,
  Upload,
  Workflow,
} from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";

type Workspace = { id: string; name: string; slug: string; description: string | null };
type DatasetList = { items: unknown[]; total: number };
type LakehouseTable = { id: string; name: string; current_layer: "BRONZE" | "SILVER" | "GOLD" };
type PipelineMetrics = {
  total_runs: number;
  status_distribution: Record<string, number>;
  average_duration_ms: number;
  retry_count: number;
  last_successful_run: string | null;
  last_failed_run: string | null;
};
type WorkerHealth = { workers: { worker_id: string; status: string; last_seen_at: string }[] };
type Run = { id: string; status: string; created_at: string; duration_ms: number | null };
type Member = { id: string; user_id: string; role: "OWNER" | "ADMIN" | "EDITOR" | "VIEWER" };

export default function WorkspaceOverviewPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const { user } = useAuth();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [datasets, setDatasets] = useState(0);
  const [tables, setTables] = useState<LakehouseTable[]>([]);
  const [storage, setStorage] = useState({ total_bytes: 0, total_objects: 0 });
  const [metrics, setMetrics] = useState<PipelineMetrics | null>(null);
  const [workers, setWorkers] = useState<WorkerHealth["workers"]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const [workspaceResult, datasetResult, tableResult, usageResult, metricsResult, workerResult, runResult, memberResult] = await Promise.all([
      api<Workspace>(`/api/v1/workspaces/${workspaceId}`),
      api<DatasetList>(`/api/v1/workspaces/${workspaceId}/datasets?page=1&page_size=1`),
      api<LakehouseTable[]>(`/api/v1/workspaces/${workspaceId}/lakehouse/tables`),
      api<{ total_bytes: number; total_objects: number }>(`/api/v1/workspaces/${workspaceId}/lakehouse/storage/usage`),
      api<PipelineMetrics>(`/api/v1/workspaces/${workspaceId}/pipelines/metrics`),
      api<WorkerHealth>(`/api/v1/workspaces/${workspaceId}/workers/health`),
      api<{ id: string }[]>(`/api/v1/workspaces/${workspaceId}/pipelines`),
      api<Member[]>(`/api/v1/workspaces/${workspaceId}/members`),
    ]);
    if (workspaceResult.error) setError(workspaceResult.error);
    else setWorkspace(workspaceResult.data ?? null);
    setDatasets(datasetResult.data?.total ?? 0);
    setTables(tableResult.data ?? []);
    if (usageResult.data) setStorage(usageResult.data);
    if (metricsResult.data) setMetrics(metricsResult.data);
    if (workerResult.data) setWorkers(workerResult.data.workers);
    const pipelineIds = runResult.data?.map((pipeline) => pipeline.id) ?? [];
    if (pipelineIds.length) {
      const runLists = await Promise.all(pipelineIds.map((pipelineId) =>
        api<Run[]>(`/api/v1/workspaces/${workspaceId}/pipelines/${pipelineId}/runs`),
      ));
      const recent = runLists.flatMap((result) => result.data ?? []).sort((a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      );
      setRuns(recent.slice(0, 5));
    } else {
      setRuns([]);
    }
    setMembers(memberResult.data ?? []);
  }, [workspaceId]);

  useEffect(() => {
    if (!user) return;
    const timeout = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timeout);
  }, [load, user]);

  const bronze = tables.filter((table) => table.current_layer === "BRONZE").length;
  const silver = tables.filter((table) => table.current_layer === "SILVER").length;
  const gold = tables.filter((table) => table.current_layer === "GOLD").length;

  return (
    <main className="min-h-[calc(100vh-64px)] px-4 py-6 md:px-7 lg:px-8">
      <div className="mx-auto max-w-[1500px]">
        {error && <div className="mb-5 rounded-lg border border-[color-mix(in_srgb,var(--danger)_35%,transparent)] bg-[color-mix(in_srgb,var(--danger)_8%,var(--surface))] px-4 py-3 text-sm">{error}</div>}

        <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-sm text-[var(--muted)]">{workspace?.slug ?? "workspace"}</p>
            <h2 className="mt-1 text-2xl font-semibold tracking-tight">{workspace?.name ?? "Workspace overview"}</h2>
          </div>
          <div className="flex gap-2">
            <Link href={`/workspaces/${workspaceId}/data`} className="flex h-9 items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm hover:border-[var(--border-strong)]">
              <Upload size={15} /> Upload
            </Link>
            <Link href={`/workspaces/${workspaceId}/sql`} className="flex h-9 items-center gap-2 rounded-md bg-[var(--accent)] px-3 text-sm font-medium text-[var(--accent-foreground)]">
              <Braces size={15} /> New query
            </Link>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard title="Datasets" value={datasets} icon={Database} detail={`${storage.total_objects} storage objects`} />
          <MetricCard title="Lakehouse tables" value={tables.length} icon={FolderKanban} detail={`${gold} Gold · ${silver} Silver`} />
          <MetricCard title="Pipeline runs" value={metrics?.total_runs ?? 0} icon={Workflow} detail={`${metrics?.status_distribution?.SUCCEEDED ?? 0} successful`} />
          <MetricCard title="Storage" value={formatBytes(storage.total_bytes)} icon={Activity} detail={`${workers.filter((worker) => worker.status !== "STALE").length} active workers`} />
        </div>

        <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(320px,.8fr)]">
          <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)]">
            <div className="flex h-14 items-center justify-between border-b border-[var(--border)] px-5">
              <div>
                <h3 className="text-sm font-semibold">Recent pipeline activity</h3>
                <p className="mt-0.5 text-xs text-[var(--muted)]">Latest workspace executions</p>
              </div>
              <Link href={`/workspaces/${workspaceId}/pipelines`} className="flex items-center gap-1 text-xs text-[var(--accent)]">
                View all <ArrowRight size={13} />
              </Link>
            </div>
            {runs.length === 0 ? (
              <EmptyState title="No pipeline runs" detail="Create and run a pipeline to see execution activity." />
            ) : (
              <div className="divide-y divide-[var(--border)]">
                {runs.map((run) => (
                  <Link key={run.id} href={`/workspaces/${workspaceId}/pipelines`} className="flex h-14 items-center px-5 hover:bg-[var(--surface-raised)]">
                    <StatusDot status={run.status} />
                    <div className="ml-3 min-w-0">
                      <p className="truncate text-sm">Pipeline run</p>
                      <p className="text-xs text-[var(--muted)]">{new Date(run.created_at).toLocaleString()}</p>
                    </div>
                    <span className="ml-auto text-xs text-[var(--muted)]">{run.duration_ms ? `${run.duration_ms} ms` : "In progress"}</span>
                  </Link>
                ))}
              </div>
            )}
          </section>

          <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)]">
            <div className="flex h-14 items-center border-b border-[var(--border)] px-5">
              <h3 className="text-sm font-semibold">Medallion distribution</h3>
            </div>
            <div className="p-5">
              <LayerBar label="Bronze" count={bronze} total={tables.length} color="var(--muted)" />
              <LayerBar label="Silver" count={silver} total={tables.length} color="var(--accent)" />
              <LayerBar label="Gold" count={gold} total={tables.length} color="var(--success)" />
            </div>
          </section>
        </div>

        <div className="mt-5 grid gap-5 lg:grid-cols-2">
          <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)]">
            <div className="flex h-14 items-center justify-between border-b border-[var(--border)] px-5">
              <h3 className="text-sm font-semibold">Workspace members</h3>
              <span className="text-xs text-[var(--muted)]">{members.length} members</span>
            </div>
            <div className="divide-y divide-[var(--border)]">
              {members.length === 0 ? (
                <EmptyState title="No member data" detail="Member details are unavailable." />
              ) : members.slice(0, 6).map((member) => (
                <div key={member.id} className="flex h-12 items-center px-5 text-sm">
                  <div className="grid size-7 place-items-center rounded-full bg-[var(--surface-hover)] text-xs">{member.user_id.slice(0, 2).toUpperCase()}</div>
                  <span className="ml-3 truncate font-mono text-xs text-[var(--muted)]">{member.user_id}</span>
                  <span className="ml-auto rounded-full border border-[var(--border)] px-2 py-1 text-xs">{member.role}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)]">
            <div className="flex h-14 items-center border-b border-[var(--border)] px-5">
              <h3 className="text-sm font-semibold">Platform status</h3>
            </div>
            <div className="p-5">
              <StatusRow label="Backend" value="Healthy" good />
              <StatusRow label="Worker" value={workers.length ? `${workers.filter((worker) => worker.status !== "STALE").length} online` : "Unavailable"} good={workers.some((worker) => worker.status !== "STALE")} />
              <StatusRow label="Average run time" value={metrics?.average_duration_ms ? `${metrics.average_duration_ms} ms` : "Unavailable"} />
              <StatusRow label="Catalog" value={tables.length ? "Discoverable" : "No assets"} good={tables.length > 0} />
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}

function MetricCard({ title, value, detail, icon: Icon }: { title: string; value: string | number; detail: string; icon: typeof Database }) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
      <div className="flex items-start justify-between">
        <p className="text-sm text-[var(--muted)]">{title}</p>
        <div className="grid size-8 place-items-center rounded-md bg-[var(--surface-hover)] text-[var(--accent)]"><Icon size={16} /></div>
      </div>
      <p className="mt-4 text-2xl font-semibold tracking-tight">{value}</p>
      <p className="mt-1 text-xs text-[var(--muted)]">{detail}</p>
    </div>
  );
}

function LayerBar({ label, count, total, color }: { label: string; count: number; total: number; color: string }) {
  const width = total ? `${Math.round((count / total) * 100)}%` : "0%";
  return (
    <div className="mb-5 last:mb-0">
      <div className="mb-2 flex justify-between text-xs"><span>{label}</span><span className="text-[var(--muted)]">{count}</span></div>
      <div className="h-1.5 overflow-hidden rounded-full bg-[var(--surface-hover)]"><div className="h-full rounded-full" style={{ width, background: color }} /></div>
    </div>
  );
}

function StatusDot({ status }: { status: string }) {
  const color = status === "SUCCEEDED" ? "var(--success)" : status === "FAILED" ? "var(--danger)" : status === "RUNNING" ? "var(--accent)" : "var(--muted)";
  return <span className="size-2 rounded-full" style={{ background: color }} />;
}

function StatusRow({ label, value, good }: { label: string; value: string; good?: boolean }) {
  return (
    <div className="flex h-10 items-center border-b border-[var(--border)] last:border-0">
      <span className="text-sm text-[var(--muted)]">{label}</span>
      <span className="ml-auto flex items-center gap-2 text-sm">{good !== undefined && <span className="size-1.5 rounded-full" style={{ background: good ? "var(--success)" : "var(--muted)" }} />}{value}</span>
    </div>
  );
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="px-5 py-10 text-center"><p className="text-sm font-medium">{title}</p><p className="mt-1 text-xs text-[var(--muted)]">{detail}</p></div>;
}

function formatBytes(bytes: number) {
  if (!bytes) return "0 B";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
