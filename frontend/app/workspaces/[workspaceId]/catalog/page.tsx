"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { useAIPageContext } from "@/components/ai-page-context";

type Asset = {
  id: string;
  asset_type: "DATASET" | "TABLE";
  name: string;
  description: string | null;
  owner_id: string | null;
  tags_json: string[];
  format: string | null;
  layer: string | null;
  created_at: string;
  updated_at: string;
};

type Schema = {
  columns: { name: string; data_type: string | null; description: string | null; business_name: string | null; glossary_term: string | null }[];
  history: { id: string; version_id: string | null; schema: Record<string, unknown>; created_at: string }[];
};

type Profile = {
  row_count: number | null;
  column_count: number | null;
  statistics: Record<string, { data_type: string; null_count: number; null_percentage: number; distinct_count: number; minimum?: unknown; maximum?: unknown; mean?: unknown }>;
  uncomputed: string[];
};

type Lineage = {
  nodes: { id: string; type: string; name: string; layer?: string; asset_type?: string; deleted?: boolean }[];
  edges: { id: string; source_asset_id: string | null; target_asset_id: string | null; relation_type: string; source_type: string; target_type: string; execution_status: string | null }[];
};

export default function CatalogPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const { user } = useAuth();
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selected, setSelected] = useState<Asset | null>(null);
  const [schema, setSchema] = useState<Schema | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [lineage, setLineage] = useState<Lineage | null>(null);
  const [search, setSearch] = useState("");
  const [layer, setLayer] = useState("");
  const [error, setError] = useState("");
  useAIPageContext({
    page_type: "catalog",
    catalog_asset_id: selected?.id,
    active_view: selected ? "asset" : "catalog",
  });

  const load = useCallback(async () => {
    const query = new URLSearchParams({ page: "1", page_size: "100" });
    if (search) query.set("search", search);
    if (layer) query.set("layer", layer);
    const response = await api<{ items: Asset[] }>(`/api/v1/workspaces/${workspaceId}/catalog?${query}`);
    if (response.error) setError(response.error);
    else setAssets(response.data?.items ?? []);
  }, [workspaceId, search, layer]);

  useEffect(() => {
    if (!user) return;
    const timeout = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timeout);
  }, [load, user]);

  const selectAsset = async (asset: Asset) => {
    setSelected(asset);
    setError("");
    setSchema(null);
    setProfile(null);
    setLineage(null);
    const [schemaResponse, profileResponse, lineageResponse] = await Promise.all([
      api<Schema>(`/api/v1/workspaces/${workspaceId}/catalog/${asset.id}/schema`),
      api<Profile>(`/api/v1/workspaces/${workspaceId}/catalog/${asset.id}/profile`),
      api<Lineage>(`/api/v1/workspaces/${workspaceId}/catalog/${asset.id}/lineage?direction=both`),
    ]);
    if (schemaResponse.error) setError(schemaResponse.error);
    else setSchema(schemaResponse.data ?? null);
    if (profileResponse.error) setError(profileResponse.error);
    else setProfile(profileResponse.data ?? null);
    if (lineageResponse.error) setError(lineageResponse.error);
    else setLineage(lineageResponse.data ?? null);
  };

  return (
    <main className="min-h-[calc(100vh-64px)] px-4 py-6 md:px-7 lg:px-8">
      <div className="mx-auto max-w-[1500px]">
        <Link href={`/workspaces/${workspaceId}`} className="text-xs text-[var(--muted)] hover:text-[var(--accent)]">Workspace / Overview</Link>
        <p className="mt-3 text-xs font-medium uppercase tracking-[0.16em] text-[var(--accent)]">Discovery</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">Data Catalog</h1>

        <div className="mt-6 grid gap-3 sm:grid-cols-3">
          <Metric label="Discoverable assets" value={assets.length} />
          <Metric label="Silver" value={assets.filter((asset) => asset.layer === "SILVER").length} />
          <Metric label="Gold" value={assets.filter((asset) => asset.layer === "GOLD").length} />
        </div>

        {error && <div className="mt-5 rounded-lg border border-[color-mix(in_srgb,var(--danger)_35%,transparent)] bg-[color-mix(in_srgb,var(--danger)_8%,var(--surface))] px-4 py-3 text-sm text-[var(--danger)]">{error}</div>}

        <div className="mt-6 grid gap-3 md:grid-cols-[1fr_180px]">
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search catalog assets" className="h-10 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 text-sm outline-none focus:border-[var(--accent)]" />
          <select value={layer} onChange={(event) => setLayer(event.target.value)} className="h-10 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 text-sm">
            <option value="">All layers</option>
            <option value="BRONZE">Bronze</option>
            <option value="SILVER">Silver</option>
            <option value="GOLD">Gold</option>
          </select>
        </div>

        <div className="mt-6 grid gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
          <div className="space-y-3">
            {assets.length === 0 ? (
              <div className="rounded-xl border border-dashed border-[var(--border-strong)] p-8 text-center text-sm text-[var(--muted)]">No catalog assets discovered.</div>
            ) : assets.map((asset) => (
              <button key={asset.id} onClick={() => void selectAsset(asset)} aria-pressed={selected?.id === asset.id} className={`w-full rounded-xl border p-4 text-left transition-colors ${selected?.id === asset.id ? "border-[var(--accent)] bg-[var(--accent-soft)]" : "border-[var(--border)] bg-[var(--surface)] hover:border-[var(--border-strong)] hover:bg-[var(--surface-raised)]"}`}>
                <p className="font-medium">{asset.name}</p>
                <p className="mt-1 text-xs text-[var(--muted)]">{asset.asset_type} · {asset.layer ?? "UNKNOWN"} · {asset.format ?? "unknown"}</p>
                {asset.tags_json.length > 0 && <p className="mt-3 text-xs text-[var(--muted)]">{asset.tags_json.join(", ")}</p>}
              </button>
            ))}
          </div>

          <section className="min-w-0 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 shadow-[var(--shadow-soft)]">
            {!selected ? (
              <p className="text-sm text-[var(--muted)]">Select a catalog asset to inspect its schema, profile and lineage.</p>
            ) : (
              <>
                <h2 className="font-medium">{selected.name}</h2>
                <p className="mt-1 text-sm text-[var(--muted)]">{selected.description || "No description"}</p>
                {selected.tags_json.length > 0 && <p className="mt-3 text-xs text-[var(--muted)]">Tags: {selected.tags_json.join(", ")}</p>}

                {profile && (
                  <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <Metric label="Rows" value={profile.row_count ?? "Unknown"} />
                    <Metric label="Columns" value={profile.column_count ?? "Unknown"} />
                    <Metric label="Profile state" value={profile.uncomputed.length ? "Partial" : "Computed"} />
                    <Metric label="Version" value={profile.uncomputed.length ? "Unavailable" : "Current"} />
                  </div>
                )}

                {schema && (
                  <div className="mt-6">
                    <h3 className="font-medium">Schema</h3>
                    <div className="mt-3 overflow-auto">
                      <table className="w-full min-w-[560px] text-left text-sm">
                        <thead><tr className="border-b border-[var(--border-strong)] text-xs text-[var(--muted)]"><th className="px-3 py-2">Column</th><th className="px-3 py-2">Type</th><th className="px-3 py-2">Documentation</th></tr></thead>
                        <tbody>{schema.columns.map((column) => (
                          <tr key={column.name} className="border-b border-[var(--border)] transition-colors hover:bg-[var(--surface-raised)]"><td className="px-3 py-2">{column.name}</td><td className="px-3 py-2 text-[var(--muted)]">{column.data_type ?? "unknown"}</td><td className="px-3 py-2">{column.description || column.business_name || "—"}</td></tr>
                        ))}</tbody>
                      </table>
                    </div>
                  </div>
                )}

                {profile?.statistics && (
                  <div className="mt-6">
                    <h3 className="font-medium">Column statistics</h3>
                    <div className="mt-3 space-y-2">{Object.entries(profile.statistics).slice(0, 20).map(([name, stats]) => (
                      <div key={name} className="rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-3 text-sm">
                        <span className="font-medium">{name}</span>
                        <span className="ml-3 text-xs text-[var(--muted)]">{stats.data_type} · {stats.distinct_count} distinct · {stats.null_count} null</span>
                      </div>
                    ))}</div>
                  </div>
                )}

                {lineage && (
                  <div className="mt-6">
                    <h3 className="font-medium">Lineage</h3>
                    <div className="mt-3 flex flex-wrap items-center gap-3">
                      {lineage.nodes.map((node) => (
                        <div key={node.id} className={`rounded-lg border px-3 py-2 text-sm ${node.id === selected.id ? "border-[var(--accent)] bg-[var(--accent-soft)]" : "border-[var(--border)]"}`}>
                          {node.deleted ? "Deleted asset" : node.name}
                          {node.layer && <span className="ml-2 text-xs text-[var(--muted)]">{node.layer}</span>}
                        </div>
                      ))}
                    </div>
                    {lineage.edges.length > 0 && (
                      <div className="mt-3 space-y-1 text-xs text-[var(--muted)]">
                        {lineage.edges.map((edge) => <p key={edge.id}>{edge.source_type} → {edge.target_type}: {edge.relation_type}{edge.execution_status ? ` (${edge.execution_status})` : ""}</p>)}
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4"><p className="text-xs text-[var(--muted)]">{label}</p><p className="mt-2 text-lg font-semibold">{value}</p></div>;
}
