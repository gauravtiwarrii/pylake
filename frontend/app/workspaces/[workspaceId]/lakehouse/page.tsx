"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";

type Table = {
  id: string;
  name: string;
  description: string | null;
  current_layer: "BRONZE" | "SILVER" | "GOLD";
  created_at: string;
  updated_at: string;
};

type Version = {
  id: string;
  version_number: number;
  layer: "BRONZE" | "SILVER" | "GOLD";
  file_format: string;
  row_count: number | null;
  column_count: number | null;
  file_size_bytes: number;
  schema_json: Record<string, unknown> | null;
  created_at: string;
  status: string;
};

type Quality = {
  version_id: string;
  version_number: number;
  row_count: number;
  column_count: number;
  duplicate_rows: number;
  null_counts: Record<string, number>;
  empty_columns: string[];
  type_consistency: string;
};

function bytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export default function LakehousePage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = use(params);
  const { user } = useAuth();
  const [tables, setTables] = useState<Table[]>([]);
  const [selected, setSelected] = useState<Table | null>(null);
  const [versions, setVersions] = useState<Version[]>([]);
  const [quality, setQuality] = useState<Quality | null>(null);
  const [usage, setUsage] = useState<{ total_bytes: number; total_objects: number } | null>(null);
  const [layer, setLayer] = useState("");
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    const query = new URLSearchParams();
    if (layer) query.set("layer", layer);
    if (search) query.set("search", search);
    const [tableResult, usageResult] = await Promise.all([
      api<Table[]>(`/api/v1/workspaces/${workspaceId}/lakehouse/tables?${query}`),
      api<{ total_bytes: number; total_objects: number }>(`/api/v1/workspaces/${workspaceId}/lakehouse/storage/usage`),
    ]);
    if (tableResult.error) setError(tableResult.error);
    else setTables(tableResult.data ?? []);
    if (!usageResult.error) setUsage(usageResult.data ?? null);
  }, [layer, search, workspaceId]);

  useEffect(() => {
    if (!user) return;
    const timeout = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timeout);
  }, [load, user]);

  const selectTable = async (table: Table) => {
    setSelected(table);
    setVersions([]);
    setQuality(null);
    setError("");
    const [versionsResult, qualityResult] = await Promise.all([
      api<Version[]>(`/api/v1/workspaces/${workspaceId}/lakehouse/tables/${table.id}/versions`),
      api<Quality>(`/api/v1/workspaces/${workspaceId}/lakehouse/tables/${table.id}/quality`),
    ]);
    if (versionsResult.error) setError(versionsResult.error);
    else setVersions(versionsResult.data ?? []);
    if (!qualityResult.error) setQuality(qualityResult.data ?? null);
  };

  const promote = async (target: "SILVER" | "GOLD") => {
    if (!selected) return;
    setError("");
    const result = await api<Version>(
      `/api/v1/workspaces/${workspaceId}/lakehouse/tables/${selected.id}/promote`,
      { method: "POST", body: JSON.stringify({ target_layer: target }) },
    );
    if (result.error) setError(result.error);
    else {
      await load();
      await selectTable(selected);
    }
  };

  return (
    <main className="min-h-screen px-6 py-8 md:px-10">
      <div className="mx-auto max-w-7xl">
        <Link href={`/workspaces/${workspaceId}`} className="text-sm text-[#98a0b3]">Back to workspace</Link>
        <h1 className="mt-2 text-3xl font-semibold">Lakehouse Explorer</h1>

        <div className="mt-6 grid gap-3 md:grid-cols-3">
          {(["BRONZE", "SILVER", "GOLD"] as const).map((item) => (
            <button
              key={item}
              onClick={() => setLayer(layer === item ? "" : item)}
              className={`rounded-lg border p-4 text-left ${layer === item ? "border-[#7dd3fc] bg-[#11141b]" : "border-[#242936] bg-[#0d1016]"}`}
            >
              <p className="text-xs text-[#98a0b3]">{item} LAYER</p>
              <p className="mt-2 text-sm">
                {item === "BRONZE" ? "Immutable source data" : item === "SILVER" ? "Standardized Parquet" : "Analytics-ready data"}
              </p>
            </button>
          ))}
        </div>

        {usage && (
          <div className="mt-4 rounded-lg border border-[#242936] bg-[#11141b] p-4 text-sm">
            <span className="text-[#98a0b3]">Actual lakehouse storage:</span>{" "}
            <strong>{bytes(usage.total_bytes)}</strong> across {usage.total_objects} objects
          </div>
        )}

        {error && <div className="mt-5 rounded-md border border-red-900 bg-red-950/40 px-4 py-3 text-sm text-red-300">{error}</div>}

        <div className="mt-6">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search lakehouse tables"
            className="h-10 w-full rounded-md border border-[#303646] bg-[#11141b] px-3 text-sm outline-none focus:border-[#7dd3fc]"
          />
        </div>

        <div className="mt-6 grid gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
          <div className="space-y-3">
            {tables.length === 0 ? (
              <div className="rounded-lg border border-dashed border-[#303646] p-6 text-sm text-[#98a0b3]">No lakehouse tables found.</div>
            ) : tables.map((table) => (
              <button
                key={table.id}
                onClick={() => void selectTable(table)}
                className={`w-full rounded-lg border p-4 text-left ${selected?.id === table.id ? "border-[#7dd3fc] bg-[#11141b]" : "border-[#242936] bg-[#0d1016]"}`}
              >
                <p className="font-medium">{table.name}</p>
                <p className="mt-1 text-xs text-[#98a0b3]">{table.current_layer}</p>
              </button>
            ))}
          </div>

          <section className="rounded-lg border border-[#242936] bg-[#11141b] p-5">
            {!selected ? (
              <p className="text-sm text-[#98a0b3]">Select a table to view versions and quality.</p>
            ) : (
              <>
                <div className="flex items-start justify-between">
                  <div>
                    <h2 className="font-medium">{selected.name}</h2>
                    <p className="mt-1 text-sm text-[#98a0b3]">Current layer: {selected.current_layer}</p>
                  </div>
                  <div className="flex gap-2">
                    {selected.current_layer === "BRONZE" && (
                      <button onClick={() => void promote("SILVER")} className="h-9 rounded-md bg-[#7dd3fc] px-3 text-sm font-medium text-[#071018]">Promote to Silver</button>
                    )}
                    {selected.current_layer === "SILVER" && (
                      <button onClick={() => void promote("GOLD")} className="h-9 rounded-md bg-[#7dd3fc] px-3 text-sm font-medium text-[#071018]">Promote to Gold</button>
                    )}
                  </div>
                </div>

                {quality && (
                  <div className="mt-5 grid gap-3 sm:grid-cols-3">
                    <Metric label="Rows" value={quality.row_count.toLocaleString()} />
                    <Metric label="Columns" value={quality.column_count.toLocaleString()} />
                    <Metric label="Duplicate rows" value={quality.duplicate_rows.toLocaleString()} />
                  </div>
                )}

                <h3 className="mt-6 font-medium">Version history</h3>
                <div className="mt-3 divide-y divide-[#242936]">
                  {versions.map((version) => (
                    <div key={version.id} className="flex items-center justify-between py-3 text-sm">
                      <div>
                        <p>Version {version.version_number} · {version.layer}</p>
                        <p className="mt-1 text-xs text-[#98a0b3]">{version.row_count ?? "—"} rows · {bytes(version.file_size_bytes)}</p>
                      </div>
                      <span className="text-xs text-[#98a0b3]">{version.status}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-md border border-[#242936] p-3"><p className="text-xs text-[#98a0b3]">{label}</p><p className="mt-1 font-medium">{value}</p></div>;
}
