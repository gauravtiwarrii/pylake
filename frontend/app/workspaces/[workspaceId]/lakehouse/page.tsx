"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  Check,
  ChevronRight,
  CircleHelp,
  Database,
  History,
  Layers3,
  RefreshCw,
  RotateCcw,
  Search,
  SlidersHorizontal,
  Table2,
  X,
  Zap,
} from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";

type Layer = "BRONZE" | "SILVER" | "GOLD";
type Role = "OWNER" | "ADMIN" | "EDITOR" | "VIEWER";
type TransformType =
  | "deduplicate"
  | "cast"
  | "rename"
  | "drop"
  | "filter"
  | "fill_null"
  | "sort"
  | "select"
  | "calculated"
  | "normalize_names";
type Table = {
  id: string;
  name: string;
  description: string | null;
  current_layer: Layer;
  created_at: string;
  updated_at: string;
};
type Column = { name: string; type: string; nullable?: boolean };
type Version = {
  id: string;
  dataset_id: string;
  version_number: number;
  layer: Layer;
  file_format: string;
  row_count: number | null;
  column_count: number | null;
  file_size_bytes: number;
  schema_json: { columns?: Column[]; partition_columns?: string[] } | null;
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
type Preview = {
  columns: Column[];
  rows: Record<string, unknown>[];
  row_count: number;
  returned_rows: number;
};
type StorageUsage = {
  total_bytes: number;
  total_objects: number;
  by_layer: Partial<Record<Layer, { bytes: number; objects: number }>>;
};
type CatalogAsset = { id: string; asset_type: string; lakehouse_table_id: string | null };
type Lineage = {
  nodes: { id: string; name: string; asset_type?: string; layer?: string; deleted?: boolean }[];
  edges: {
    id: string;
    source_asset_id: string | null;
    target_asset_id: string | null;
    relation_type: string;
    execution_status: string | null;
    execution_id: string | null;
    metadata: Record<string, unknown>;
    created_at: string;
  }[];
};
type ConfirmAction = {
  kind: "promote" | "restore";
  sourceVersion: Version;
  targetLayer: Exclude<Layer, "BRONZE">;
};
type Tab = "overview" | "schema" | "preview" | "versions" | "quality" | "lineage" | "transform";

const layers: { id: Layer; title: string; subtitle: string; description: string; icon: typeof Database }[] = [
  { id: "BRONZE", title: "Bronze", subtitle: "Source", description: "Original ingested data", icon: Database },
  { id: "SILVER", title: "Silver", subtitle: "Refined", description: "Cleaned and standardized", icon: Layers3 },
  { id: "GOLD", title: "Gold", subtitle: "Analytics", description: "Analytics-ready assets", icon: Activity },
];
const tabs: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "schema", label: "Schema" },
  { id: "preview", label: "Preview" },
  { id: "versions", label: "Versions" },
  { id: "quality", label: "Quality" },
  { id: "lineage", label: "Lineage" },
  { id: "transform", label: "Transform" },
];
const transformLabels: Record<TransformType, string> = {
  deduplicate: "Deduplicate rows",
  cast: "Cast column type",
  rename: "Rename column",
  drop: "Remove columns",
  filter: "Filter rows",
  fill_null: "Fill null values",
  sort: "Sort rows",
  select: "Select columns",
  calculated: "Add calculated column",
  normalize_names: "Normalize column names",
};

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function formatDate(value: string) {
  return new Date(value).toLocaleString();
}

function prettyValue(value: unknown) {
  if (value === null || value === undefined) return "null";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function layerColor(layer: Layer) {
  if (layer === "BRONZE") return "var(--warning)";
  if (layer === "SILVER") return "var(--accent)";
  return "var(--success)";
}

export default function LakehousePage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const { user } = useAuth();
  const [tables, setTables] = useState<Table[]>([]);
  const [selected, setSelected] = useState<Table | null>(null);
  const [versions, setVersions] = useState<Version[]>([]);
  const [activeVersionId, setActiveVersionId] = useState("");
  const [quality, setQuality] = useState<Quality | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [lineage, setLineage] = useState<Lineage | null>(null);
  const [lineageMessage, setLineageMessage] = useState("");
  const [tableAssetId, setTableAssetId] = useState("");
  const [sourceDatasetName, setSourceDatasetName] = useState("");
  const [usage, setUsage] = useState<StorageUsage | null>(null);
  const [role, setRole] = useState<Role | null>(null);
  const [roleMessage, setRoleMessage] = useState("");
  const [layerFilter, setLayerFilter] = useState<Layer | "">("");
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<Tab>("overview");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [qualityLoading, setQualityLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null);
  const [operation, setOperation] = useState<TransformType>("deduplicate");
  const [sourceVersionId, setSourceVersionId] = useState("");
  const [targetLayer, setTargetLayer] = useState<Exclude<Layer, "BRONZE">>("SILVER");
  const [columnText, setColumnText] = useState("");
  const [sourceColumn, setSourceColumn] = useState("");
  const [newColumnName, setNewColumnName] = useState("");
  const [castType, setCastType] = useState("string");
  const [filterOperator, setFilterOperator] = useState("eq");
  const [filterValue, setFilterValue] = useState("");
  const [fillValue, setFillValue] = useState("");
  const [calculatedName, setCalculatedName] = useState("");
  const [calculatedOperator, setCalculatedOperator] = useState("add");
  const [calculatedOperand, setCalculatedOperand] = useState("");
  const [sortDescending, setSortDescending] = useState(false);
  const requestId = useRef(0);
  const detailRequestId = useRef(0);
  const qualityRequestId = useRef(0);

  const canWrite = role === "OWNER" || role === "ADMIN" || role === "EDITOR";
  const activeVersion = versions.find((version) => version.id === activeVersionId) ?? null;
  const columns = activeVersion?.schema_json?.columns ?? [];
  const selectedLineageNodes = useMemo(() => {
    if (!tableAssetId || !lineage) return [];
    const assetIds = new Set(lineage.nodes.filter((node) => node.asset_type === "DATASET").map((node) => node.id));
    const sourceIds = new Set(
      lineage.edges
        .filter((edge) => edge.target_asset_id === tableAssetId)
        .map((edge) => edge.source_asset_id)
        .filter((id): id is string => id !== null && assetIds.has(id)),
    );
    return lineage.nodes.filter((node) => sourceIds.has(node.id));
  }, [lineage, tableAssetId]);

  const load = useCallback(async () => {
    const currentRequest = ++requestId.current;
    setLoading(true);
    setError("");
    const [tableResult, usageResult] = await Promise.all([
      api<Table[]>(`/api/v1/workspaces/${workspaceId}/lakehouse/tables`),
      api<StorageUsage>(`/api/v1/workspaces/${workspaceId}/lakehouse/storage/usage`),
    ]);
    if (currentRequest !== requestId.current) return undefined;
    setLoading(false);
    if (tableResult.error) setError(tableResult.error);
    const nextTables = tableResult.data ?? [];
    if (!tableResult.error) setTables(nextTables);
    if (usageResult.error) setError((current) => current || usageResult.error || "");
    else setUsage(usageResult.data ?? null);
    return tableResult.error ? undefined : nextTables;
  }, [workspaceId]);

  useEffect(() => {
    if (!user) return;
    const timeout = window.setTimeout(() => void load(), 250);
    return () => window.clearTimeout(timeout);
  }, [load, user]);

  useEffect(() => {
    if (!user) return;
    let active = true;
    api<{ user_id: string; role: Role }[]>(`/api/v1/workspaces/${workspaceId}/members`).then((result) => {
      if (!active) return;
      if (result.error) setRoleMessage(result.error);
      else setRole(result.data?.find((member) => member.user_id === user.id)?.role ?? null);
    });
    return () => {
      active = false;
    };
  }, [user, workspaceId]);

  const loadQuality = useCallback(async (tableId: string, versionId: string) => {
    const currentRequest = ++qualityRequestId.current;
    setQualityLoading(true);
    const result = await api<Quality>(
      `/api/v1/workspaces/${workspaceId}/lakehouse/tables/${tableId}/quality?version_id=${encodeURIComponent(versionId)}`,
    );
    if (currentRequest !== qualityRequestId.current) return;
    setQualityLoading(false);
    if (result.error) setError(result.error);
    else setQuality(result.data ?? null);
  }, [workspaceId]);

  const selectTable = async (table: Table) => {
    const currentRequest = ++detailRequestId.current;
    setSelected(table);
    setTab("overview");
    setDetailLoading(true);
    setVersions([]);
    setActiveVersionId("");
    setQuality(null);
    setPreview(null);
    setPreviewError("");
    setLineage(null);
    setLineageMessage("");
    setTableAssetId("");
    setSourceDatasetName("");
    setTargetLayer(table.current_layer === "GOLD" ? "GOLD" : "SILVER");
    setError("");
    const [versionResult, assetResult] = await Promise.all([
      api<Version[]>(`/api/v1/workspaces/${workspaceId}/lakehouse/tables/${table.id}/versions`),
      api<{ items: CatalogAsset[] }>(
        `/api/v1/workspaces/${workspaceId}/catalog?page=1&page_size=100&search=${encodeURIComponent(table.name)}`,
      ),
    ]);
    if (currentRequest !== detailRequestId.current) return;
    setDetailLoading(false);
    if (versionResult.error) setError(versionResult.error);
    const nextVersions = [...(versionResult.data ?? [])].sort((a, b) => b.version_number - a.version_number);
    setVersions(nextVersions);
    const latest = nextVersions.find((version) => version.status === "COMPLETED") ?? nextVersions[0];
    if (latest) {
      setActiveVersionId(latest.id);
      setSourceVersionId(latest.id);
      if (latest.status === "COMPLETED") void loadQuality(table.id, latest.id);
    }
    const sourceVersion = [...nextVersions].reverse().find((version) => version.layer === "BRONZE") ?? nextVersions[0];
    if (sourceVersion?.dataset_id) {
      const [previewResult, datasetResult] = await Promise.all([
        api<Preview>(`/api/v1/workspaces/${workspaceId}/datasets/${sourceVersion.dataset_id}/preview?limit=50`),
        api<{ name: string }>(`/api/v1/workspaces/${workspaceId}/datasets/${sourceVersion.dataset_id}`),
      ]);
      if (currentRequest !== detailRequestId.current) return;
      if (previewResult.error) setPreviewError(previewResult.error);
      else setPreview(previewResult.data ?? null);
      setSourceDatasetName(datasetResult.data?.name ?? "");
    } else {
      setPreviewError("No source dataset is associated with this table.");
    }
    if (assetResult.error) {
      setLineageMessage(assetResult.error);
      return;
    }
    const asset = assetResult.data?.items.find(
      (item) => item.asset_type === "TABLE" && item.lakehouse_table_id === table.id,
    );
    if (!asset) {
      setLineageMessage("No catalog lineage asset is available for this table.");
      return;
    }
    setTableAssetId(asset.id);
    const lineageResult = await api<Lineage>(
      `/api/v1/workspaces/${workspaceId}/catalog/${asset.id}/lineage?direction=both`,
    );
    if (currentRequest !== detailRequestId.current) return;
    if (lineageResult.error) setLineageMessage(lineageResult.error);
    else setLineage(lineageResult.data ?? null);
  };

  const inspectVersion = (version: Version) => {
    setActiveVersionId(version.id);
    setQuality(null);
    if (selected && version.status === "COMPLETED") void loadQuality(selected.id, version.id);
  };

  const requestPromote = (target: Exclude<Layer, "BRONZE">) => {
    if (!selected || !activeVersion) return;
    if (activeVersion.status !== "COMPLETED") {
      setError("Only completed versions can be promoted.");
      return;
    }
    const rank = { BRONZE: 1, SILVER: 2, GOLD: 3 };
    if (rank[target] < rank[activeVersion.layer]) {
      setError(`A ${activeVersion.layer} version cannot be promoted backward to ${target}.`);
      return;
    }
    setConfirmAction({ kind: "promote", sourceVersion: activeVersion, targetLayer: target });
  };

  const confirmVersionAction = async () => {
    if (!selected || !confirmAction) return;
    setActionLoading(true);
    setError("");
    setNotice("");
    const body = {
      target_layer: confirmAction.targetLayer,
      source_version_id: confirmAction.sourceVersion.id,
    };
    const result = await api<Version>(
      `/api/v1/workspaces/${workspaceId}/lakehouse/tables/${selected.id}/promote`,
      { method: "POST", body: JSON.stringify(body) },
    );
    setActionLoading(false);
    if (result.error) {
      setError(result.error);
      return;
    }
    const actionLabel = confirmAction.kind === "restore" ? "Restore" : "Promotion";
    setNotice(`${actionLabel} created version ${result.data?.version_number ?? ""} in ${confirmAction.targetLayer}.`);
    const updatedTable = { ...selected, current_layer: confirmAction.targetLayer };
    setConfirmAction(null);
    const refreshedTables = await load();
    await selectTable(refreshedTables?.find((table) => table.id === selected.id) ?? updatedTable);
  };

  const buildTransformConfig = (): { configuration?: Record<string, unknown>; error?: string } => {
    const chosenColumns = columnText.split(",").map((value) => value.trim()).filter(Boolean);
    const knownColumns = new Set(columns.map((column) => column.name));
    const unknownColumns = chosenColumns.filter((column) => !knownColumns.has(column));
    if (unknownColumns.length) return { error: `Unknown column${unknownColumns.length > 1 ? "s" : ""}: ${unknownColumns.join(", ")}` };
    if (["drop", "select", "sort"].includes(operation) && chosenColumns.length === 0) {
      return { error: "Enter at least one column name, separated by commas." };
    }
    if (operation === "deduplicate") return { configuration: chosenColumns.length ? { columns: chosenColumns } : {} };
    if (operation === "normalize_names") return { configuration: {} };
    if (operation === "drop" || operation === "select") return { configuration: { columns: chosenColumns } };
    if (operation === "sort") return { configuration: { columns: chosenColumns, descending: sortDescending } };
    if (operation === "rename") {
      if (!sourceColumn || !knownColumns.has(sourceColumn) || !newColumnName.trim()) return { error: "Choose a column and enter its new name." };
      if (knownColumns.has(newColumnName.trim()) && newColumnName.trim() !== sourceColumn) return { error: "That column name already exists." };
      return { configuration: { mapping: { [sourceColumn]: newColumnName.trim() } } };
    }
    if (operation === "cast") {
      if (!sourceColumn || !knownColumns.has(sourceColumn)) return { error: "Choose a column to cast." };
      return { configuration: { columns: { [sourceColumn]: castType } } };
    }
    if (operation === "filter") {
      if (!sourceColumn || !knownColumns.has(sourceColumn) || !filterValue.trim()) return { error: "Choose a column and enter a filter value." };
      const columnType = columns.find((column) => column.name === sourceColumn)?.type.toLowerCase() ?? "";
      let value: string | number | boolean = filterValue;
      if (/^(u?int|i\d+|u\d+)/.test(columnType)) {
        const parsed = Number.parseInt(filterValue, 10);
        if (!Number.isFinite(parsed)) return { error: "Enter a valid integer filter value." };
        value = parsed;
      } else if (/^(float|decimal|double|f\d+)/.test(columnType)) {
        const parsed = Number(filterValue);
        if (!Number.isFinite(parsed)) return { error: "Enter a valid numeric filter value." };
        value = parsed;
      } else if (columnType.includes("bool")) {
        if (!["true", "false"].includes(filterValue.toLowerCase())) return { error: "Enter true or false for a boolean column." };
        value = filterValue.toLowerCase() === "true";
      }
      return { configuration: { expression: { column: sourceColumn, operator: filterOperator, value } } };
    }
    if (operation === "fill_null") {
      if (!sourceColumn || !knownColumns.has(sourceColumn)) return { error: "Choose a column to fill." };
      const columnType = columns.find((column) => column.name === sourceColumn)?.type.toLowerCase() ?? "";
      let value: string | number | boolean = fillValue;
      if (/^(u?int|i\d+|u\d+)/.test(columnType)) {
        const parsed = Number.parseInt(fillValue, 10);
        if (!Number.isFinite(parsed)) return { error: "Enter a valid integer replacement value." };
        value = parsed;
      } else if (/^(float|decimal|double|f\d+)/.test(columnType)) {
        const parsed = Number(fillValue);
        if (!Number.isFinite(parsed)) return { error: "Enter a valid numeric replacement value." };
        value = parsed;
      } else if (columnType.includes("bool")) {
        if (!["true", "false"].includes(fillValue.toLowerCase())) return { error: "Enter true or false for a boolean column." };
        value = fillValue.toLowerCase() === "true";
      }
      return { configuration: { columns: [sourceColumn], value } };
    }
    if (operation === "calculated") {
      const operand = Number(calculatedOperand);
      if (!calculatedName.trim() || !sourceColumn || !knownColumns.has(sourceColumn) || !Number.isFinite(operand)) {
        return { error: "Enter a new column name, a source column, and a valid numeric operand." };
      }
      if (knownColumns.has(calculatedName.trim())) return { error: "That column name already exists." };
      return { configuration: { name: calculatedName.trim(), source_column: sourceColumn, operator: calculatedOperator, operand } };
    }
    return { error: "Choose a supported transformation." };
  };

  const submitTransform = async () => {
    if (!selected || !canWrite || !sourceVersionId) return;
    const built = buildTransformConfig();
    if (built.error || !built.configuration) {
      setError(built.error ?? "Transformation configuration is invalid.");
      return;
    }
    setActionLoading(true);
    setError("");
    setNotice("");
    const result = await api<Version>(
      `/api/v1/workspaces/${workspaceId}/lakehouse/tables/${selected.id}/transform`,
      {
        method: "POST",
        body: JSON.stringify({
          source_version_id: sourceVersionId,
          transformation_type: operation,
          configuration: built.configuration,
          target_layer: targetLayer,
        }),
      },
    );
    setActionLoading(false);
    if (result.error) {
      setError(result.error);
      return;
    }
    setNotice(`Transformation completed and created version ${result.data?.version_number ?? ""}.`);
    const updatedTable = { ...selected, current_layer: targetLayer };
    const refreshedTables = await load();
    await selectTable(refreshedTables?.find((table) => table.id === selected.id) ?? updatedTable);
  };

  const visibleTables = useMemo(() => tables.filter((table) => {
    const matchesLayer = !layerFilter || table.current_layer === layerFilter;
    const matchesSearch = !search.trim() || table.name.toLowerCase().includes(search.trim().toLowerCase());
    return matchesLayer && matchesSearch;
  }), [layerFilter, search, tables]);

  const layerCounts = useMemo(() => ({
    BRONZE: tables.filter((table) => table.current_layer === "BRONZE").length,
    SILVER: tables.filter((table) => table.current_layer === "SILVER").length,
    GOLD: tables.filter((table) => table.current_layer === "GOLD").length,
  }), [tables]);

  const sourceNames = selectedLineageNodes.map((node) => node.name);
  const recordedSources = sourceNames.length ? sourceNames.join(", ") : sourceDatasetName;
  const partitionColumns = activeVersion?.schema_json?.partition_columns ?? [];

  return (
    <main className="min-h-[calc(100vh-64px)] px-4 py-6 md:px-7 lg:px-8">
      <div className="mx-auto max-w-[1500px]">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.16em] text-[var(--accent)]">
              <Link href={`/workspaces/${workspaceId}`} className="hover:text-[var(--foreground)]">Workspace</Link>
              <ChevronRight size={13} />
              Lakehouse
            </div>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight">Lakehouse Explorer</h2>
            <p className="mt-1 text-sm text-[var(--muted)]">Explore medallion layers, table versions, quality, and lineage.</p>
          </div>
          <button onClick={() => void load()} className="flex h-9 items-center justify-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 text-sm hover:border-[var(--border-strong)]">
            <RefreshCw size={14} /> Refresh
          </button>
        </div>

        <div className="mt-6 grid gap-3 sm:grid-cols-3">
          {layers.map(({ id, title, subtitle, description, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setLayerFilter(layerFilter === id ? "" : id)}
              aria-pressed={layerFilter === id}
              className={`rounded-xl border bg-[var(--surface)] p-4 text-left transition-colors ${layerFilter === id ? "border-[var(--accent)]" : "border-[var(--border)] hover:border-[var(--border-strong)]"}`}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <span className="grid size-9 place-items-center rounded-lg border border-[var(--border)] bg-[var(--surface-raised)]" style={{ color: layerColor(id) }}><Icon size={17} /></span>
                  <div><p className="text-sm font-semibold">{title} <span className="font-normal text-[var(--muted)]">{subtitle}</span></p><p className="mt-1 text-xs text-[var(--muted)]">{description}</p></div>
                </div>
                <span className="rounded-full border border-[var(--border)] px-2 py-1 text-xs">{layerCounts[id]}</span>
              </div>
            </button>
          ))}
        </div>

        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <SummaryCard icon={Table2} label="Lakehouse tables" value={tables.length.toLocaleString()} detail="Tables in the current workspace" />
          <SummaryCard icon={Database} label="Storage used" value={usage ? formatBytes(usage.total_bytes) : "Unavailable"} detail={usage ? `${usage.total_objects} stored objects across layers` : "Storage usage is unavailable"} />
        </div>

        {usage && (
          <section className="mt-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
            <div className="mb-3 flex items-center gap-2 text-xs font-medium text-[var(--muted)]"><SlidersHorizontal size={14} /> Storage by layer</div>
            <div className="grid gap-3 sm:grid-cols-3">
              {layers.map(({ id, title }) => {
                const layerUsage = usage.by_layer?.[id];
                return <div key={id} className="flex items-center justify-between rounded-lg bg-[var(--surface-raised)] px-3 py-2 text-sm"><span>{title}</span><span className="text-[var(--muted)]">{layerUsage ? `${formatBytes(layerUsage.bytes)} · ${layerUsage.objects} objects` : "No recorded objects"}</span></div>;
              })}
            </div>
          </section>
        )}

        {notice && <Notice kind="success" message={notice} onDismiss={() => setNotice("")} />}
        {error && <Notice kind="error" message={error} onDismiss={() => setError("")} />}
        {roleMessage && <Notice kind="error" message={`Could not verify workspace permissions: ${roleMessage}`} onDismiss={() => setRoleMessage("")} />}

        <div className="mt-5 grid min-h-[650px] gap-5 xl:grid-cols-[minmax(300px,0.72fr)_minmax(0,1.8fr)]">
          <section className="min-w-0 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
            <div className="border-b border-[var(--border)] p-3">
              <label className="relative block">
                <Search size={15} className="absolute left-3 top-3 text-[var(--muted)]" />
                <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search tables" className="h-10 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] pl-9 pr-3 text-sm outline-none focus:border-[var(--accent)]" />
              </label>
              <div className="mt-3 flex gap-1 overflow-x-auto">
                {(["", "BRONZE", "SILVER", "GOLD"] as const).map((item) => (
                  <button key={item || "all"} onClick={() => setLayerFilter(item)} className={`shrink-0 rounded-md px-2.5 py-1.5 text-xs ${layerFilter === item ? "bg-[var(--surface-hover)] text-[var(--foreground)]" : "text-[var(--muted)] hover:bg-[var(--surface-raised)]"}`}>
                    {item || "All layers"}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex h-10 items-center justify-between border-b border-[var(--border)] px-4 text-xs text-[var(--muted)]">
              <span>{loading ? "Loading tables..." : `${visibleTables.length} ${visibleTables.length === 1 ? "table" : "tables"}`}</span>
              {layerFilter && <button onClick={() => setLayerFilter("")} className="hover:text-[var(--foreground)]">Clear filter</button>}
            </div>
            {loading ? (
              <div className="space-y-2 p-3">{[0, 1, 2, 3].map((item) => <div key={item} className="h-[68px] animate-pulse rounded-lg bg-[var(--surface-raised)]" />)}</div>
            ) : visibleTables.length === 0 ? (
              <EmptyState title="No tables found" detail={search || layerFilter ? "Try a different search or layer filter." : "Upload a dataset to create your first Bronze table."} />
            ) : (
              <div className="max-h-[690px] overflow-y-auto p-2">
                {visibleTables.map((table) => {
                  const Icon = layers.find((item) => item.id === table.current_layer)?.icon ?? Table2;
                  return (
                    <button key={table.id} onClick={() => void selectTable(table)} aria-pressed={selected?.id === table.id} className={`mb-1 w-full rounded-lg border p-3 text-left transition-colors ${selected?.id === table.id ? "border-[var(--accent)] bg-[var(--surface-raised)]" : "border-transparent hover:bg-[var(--surface-raised)]"}`}>
                      <div className="flex items-center gap-3">
                        <span className="grid size-9 shrink-0 place-items-center rounded-lg border border-[var(--border)] bg-[var(--surface)]" style={{ color: layerColor(table.current_layer) }}><Icon size={16} /></span>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium">{table.name}</p>
                          <p className="mt-1 truncate text-xs text-[var(--muted)]">{table.current_layer} · Updated {formatDate(table.updated_at)}</p>
                        </div>
                        <ChevronRight size={15} className="shrink-0 text-[var(--muted)]" />
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </section>

          <section className="min-w-0 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
            {!selected ? (
              <EmptyState title="Select a lakehouse table" detail="Choose a table to inspect its latest version, schema, preview, quality, and lineage." />
            ) : (
              <>
                <div className="border-b border-[var(--border)] px-4 pt-4 md:px-5">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="truncate text-lg font-semibold">{selected.name}</h3>
                        <LayerBadge layer={selected.current_layer} />
                      </div>
                      <p className="mt-1 text-sm text-[var(--muted)]">{selected.description || "No table description"}</p>
                      {recordedSources && <p className="mt-1 text-xs text-[var(--muted)]">Source dataset{sourceNames.length > 1 ? "s" : ""}: {recordedSources}</p>}
                    </div>
                    <div className="flex shrink-0 flex-wrap gap-2">
                      {canWrite && selected.current_layer === "BRONZE" && activeVersion?.status === "COMPLETED" && (
                        <button onClick={() => requestPromote("SILVER")} className="flex h-9 items-center gap-2 rounded-lg bg-[var(--accent)] px-3 text-sm font-medium text-[var(--accent-foreground)]"><ArrowUpRight size={14} /> Promote to Silver</button>
                      )}
                      {canWrite && selected.current_layer === "SILVER" && activeVersion?.status === "COMPLETED" && (
                        <button onClick={() => requestPromote("GOLD")} className="flex h-9 items-center gap-2 rounded-lg bg-[var(--accent)] px-3 text-sm font-medium text-[var(--accent-foreground)]"><ArrowUpRight size={14} /> Promote to Gold</button>
                      )}
                      {role && <span className="flex h-9 items-center rounded-lg border border-[var(--border)] px-2.5 text-xs text-[var(--muted)]">{role}</span>}
                    </div>
                  </div>
                  <div className="mt-4 flex gap-1 overflow-x-auto scrollbar-thin" role="tablist" aria-label="Table details">
                    {tabs.map((item) => (
                      <button key={item.id} id={`lakehouse-tab-${item.id}`} role="tab" aria-selected={tab === item.id} aria-controls="lakehouse-tab-panel" onClick={() => setTab(item.id)} className={`shrink-0 border-b-2 px-3 py-2.5 text-xs font-medium ${tab === item.id ? "border-[var(--accent)] text-[var(--foreground)]" : "border-transparent text-[var(--muted)] hover:text-[var(--foreground)]"}`}>
                        {item.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div id="lakehouse-tab-panel" role="tabpanel" aria-labelledby={`lakehouse-tab-${tab}`} className="max-h-[720px] min-h-[430px] overflow-auto p-4 md:p-5">
                  {detailLoading ? <LoadingDetails /> : !activeVersion ? (
                    <EmptyState title="Version metadata unavailable" detail="No versions are currently recorded for this table." />
                  ) : (
                    <>
                      {tab === "overview" && (
                        <div className="space-y-5">
                          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                            <Metric label="Latest version" value={`v${activeVersion.version_number}`} detail={activeVersion.status} />
                            <Metric label="Rows" value={activeVersion.row_count?.toLocaleString() ?? "Unavailable"} detail="Latest completed version" />
                            <Metric label="Columns" value={activeVersion.column_count?.toLocaleString() ?? "Unavailable"} detail="Latest completed version" />
                            <Metric label="File size" value={formatBytes(activeVersion.file_size_bytes)} detail={activeVersion.file_format.toUpperCase()} />
                          </div>
                          <div className="grid gap-5 lg:grid-cols-2">
                            <Panel title="Version details" icon={History}>
                              <DetailRow label="Layer" value={activeVersion.layer} />
                              <DetailRow label="Status" value={activeVersion.status} />
                              <DetailRow label="Created" value={formatDate(activeVersion.created_at)} />
                              <DetailRow label="Table updated" value={formatDate(selected.updated_at)} />
                            </Panel>
                            <Panel title="Data quality" icon={Activity}>
                              {qualityLoading ? <InlineLoading /> : quality ? (
                                <>
                                  <DetailRow label="Duplicate rows" value={quality.duplicate_rows.toLocaleString()} />
                                  <DetailRow label="Columns with nulls" value={Object.values(quality.null_counts).filter((count) => count > 0).length.toLocaleString()} />
                                  <DetailRow label="Empty columns" value={quality.empty_columns.length.toLocaleString()} />
                                  <DetailRow label="Type consistency" value={quality.type_consistency} />
                                </>
                              ) : <p className="text-sm text-[var(--muted)]">Quality summary is unavailable for this version.</p>}
                            </Panel>
                          </div>
                          <Panel title="Storage and partition metadata" icon={Database}>
                            <DetailRow label="Stored format" value={activeVersion.file_format.toUpperCase()} />
                            <DetailRow label="Object size" value={formatBytes(activeVersion.file_size_bytes)} />
                            {partitionColumns.length > 0 ? (
                              <>
                                <DetailRow label="Recorded partition columns" value={partitionColumns.join(", ")} />
                                <p className="mt-3 flex gap-2 text-xs text-[var(--muted)]"><CircleHelp size={14} className="shrink-0" />This is partition metadata only. It does not indicate Hive-style directory partitioning or partition pruning.</p>
                              </>
                            ) : <p className="mt-2 text-xs text-[var(--muted)]">No partition columns are recorded for this version.</p>}
                          </Panel>
                        </div>
                      )}

                      {tab === "schema" && (
                        columns.length ? (
                          <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
                            <table className="w-full min-w-[560px] text-left text-sm">
                              <thead className="bg-[var(--surface-raised)] text-xs text-[var(--muted)]"><tr><th className="px-4 py-3 font-medium">Position</th><th className="px-4 py-3 font-medium">Column</th><th className="px-4 py-3 font-medium">Data type</th><th className="px-4 py-3 font-medium">Nullability</th></tr></thead>
                              <tbody className="divide-y divide-[var(--border)]">{columns.map((column, index) => <tr key={`${column.name}-${index}`}><td className="px-4 py-3 text-[var(--muted)]">{index + 1}</td><td className="px-4 py-3 font-mono text-xs">{column.name}</td><td className="px-4 py-3 text-[var(--muted)]">{column.type}</td><td className="px-4 py-3 text-[var(--muted)]">{column.nullable === undefined ? "Not recorded" : column.nullable ? "Nullable" : "Non-nullable"}</td></tr>)}</tbody>
                            </table>
                          </div>
                        ) : <EmptyState title="Schema unavailable" detail="The selected version does not contain column schema metadata." />
                      )}

                      {tab === "preview" && (
                        <div>
                          <div className="mb-3 flex items-start gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-3 text-xs text-[var(--muted)]">
                            <CircleHelp size={15} className="mt-0.5 shrink-0" />
                            <p>This bounded sample uses the original Bronze dataset preview endpoint. The backend does not currently expose row previews for transformed Lakehouse versions.</p>
                          </div>
                          {previewError ? <EmptyState title="Source preview unavailable" detail={previewError} /> : !preview ? <InlineLoading /> : (
                            <>
                              <div className="mb-2 flex justify-between text-xs text-[var(--muted)]"><span>Original source sample · maximum 50 rows</span><span>{preview.returned_rows} rows returned</span></div>
                              <PreviewTable preview={preview} />
                            </>
                          )}
                        </div>
                      )}

                      {tab === "versions" && (
                        <div className="space-y-3">
                          <p className="text-sm text-[var(--muted)]">Versions are immutable records. Restoring a previous version creates a new version from its data.</p>
                          {versions.length === 0 ? <EmptyState title="No version history" detail="Version history has not been recorded." /> : versions.map((version) => {
                            const canRestore = canWrite && version.status === "COMPLETED" && version.id !== activeVersion.id && selected.current_layer !== "BRONZE" && (selected.current_layer === "GOLD" || version.layer !== "GOLD");
                            const restoreLayer = selected.current_layer === "GOLD" ? "GOLD" : "SILVER";
                            return (
                              <div key={version.id} className={`rounded-lg border p-4 ${version.id === activeVersion.id ? "border-[var(--accent)] bg-[var(--surface-raised)]" : "border-[var(--border)]"}`}>
                                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                                  <button onClick={() => inspectVersion(version)} className="min-w-0 text-left">
                                    <div className="flex flex-wrap items-center gap-2"><span className="font-medium">Version {version.version_number}</span><LayerBadge layer={version.layer} /><span className="text-xs text-[var(--muted)]">{version.status}</span>{version.id === activeVersion.id && <span className="text-xs text-[var(--accent)]">Inspecting</span>}</div>
                                    <p className="mt-1 text-xs text-[var(--muted)]">{formatDate(version.created_at)} · {version.row_count?.toLocaleString() ?? "Unknown rows"} · {version.column_count ?? "Unknown columns"} · {formatBytes(version.file_size_bytes)}</p>
                                  </button>
                                  {canRestore && <button onClick={() => setConfirmAction({ kind: "restore", sourceVersion: version, targetLayer: restoreLayer })} className="flex h-9 shrink-0 items-center justify-center gap-2 rounded-lg border border-[var(--border)] px-3 text-xs hover:border-[var(--accent)]"><RotateCcw size={14} /> Restore as {restoreLayer}</button>}
                                </div>
                                {version.schema_json?.partition_columns?.length ? <p className="mt-3 text-xs text-[var(--muted)]">Partition metadata: {version.schema_json.partition_columns.join(", ")}</p> : null}
                              </div>
                            );
                          })}
                        </div>
                      )}

                      {tab === "quality" && (
                        qualityLoading ? <InlineLoading /> : quality ? (
                          <div className="space-y-5">
                            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                              <Metric label="Rows" value={quality.row_count.toLocaleString()} detail={`Version ${quality.version_number}`} />
                              <Metric label="Columns" value={quality.column_count.toLocaleString()} detail="Measured from data" />
                              <Metric label="Duplicate rows" value={quality.duplicate_rows.toLocaleString()} detail="Exact duplicate rows" />
                              <Metric label="Type consistency" value={quality.type_consistency} detail="Backend quality summary" />
                            </div>
                            <Panel title="Null values by column" icon={Activity}>
                              {Object.keys(quality.null_counts).length ? Object.entries(quality.null_counts).map(([name, count]) => <DetailRow key={name} label={name} value={count.toLocaleString()} />) : <p className="text-sm text-[var(--muted)]">No column-level null metrics were returned.</p>}
                            </Panel>
                            <Panel title="Fully empty columns" icon={Table2}>
                              {quality.empty_columns.length ? <div className="flex flex-wrap gap-2">{quality.empty_columns.map((name) => <span key={name} className="rounded-md border border-[var(--border)] px-2.5 py-1.5 font-mono text-xs">{name}</span>)}</div> : <p className="text-sm text-[var(--muted)]">No fully empty columns were reported.</p>}
                              <p className="mt-3 text-xs text-[var(--muted)]">The quality API does not include an execution timestamp or additional validation results.</p>
                            </Panel>
                          </div>
                        ) : <EmptyState title="Quality data unavailable" detail="The backend did not return quality metrics for this version." />
                      )}

                      {tab === "lineage" && (
                        <div className="space-y-4">
                          {lineageMessage && <Notice kind="error" message={lineageMessage} />}
                          {recordedSources && <Panel title="Recorded source datasets" icon={Database}><DetailRow label="Dataset" value={recordedSources} /></Panel>}
                          <Panel title="Transformation and lineage events" icon={History}>
                            {lineage?.edges.length ? (
                              <div className="space-y-2">{[...lineage.edges].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()).map((edge) => (
                                <div key={edge.id} className="rounded-lg border border-[var(--border)] p-3">
                                  <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-sm font-medium">{String(edge.metadata.transformation_type ?? edge.relation_type)}</span><span className="text-xs text-[var(--muted)]">{edge.execution_status ?? "Status not recorded"}</span></div>
                                  <p className="mt-1 text-xs text-[var(--muted)]">{formatDate(edge.created_at)}{edge.metadata.source_version !== undefined ? ` · source v${String(edge.metadata.source_version)}` : ""}{edge.metadata.target_version !== undefined ? ` · output v${String(edge.metadata.target_version)}` : ""}</p>
                                </div>
                              ))}</div>
                            ) : <p className="text-sm text-[var(--muted)]">No lineage events are recorded for this table.</p>}
                          </Panel>
                        </div>
                      )}

                      {tab === "transform" && (
                        canWrite ? (
                          <div className="mx-auto max-w-3xl space-y-5">
                            <div>
                              <h4 className="text-sm font-semibold">Create a transformed version</h4>
                              <p className="mt-1 text-xs text-[var(--muted)]">Each operation reads the selected source version and writes a new immutable version.</p>
                            </div>
                            <div className="grid gap-4 sm:grid-cols-2">
                              <FormField label="Source version">
                                <select value={sourceVersionId || activeVersion.id} onChange={(event) => setSourceVersionId(event.target.value)} className={inputClass}>
                                  {versions.filter((version) => version.status === "COMPLETED").map((version) => <option key={version.id} value={version.id}>v{version.version_number} · {version.layer}</option>)}
                                </select>
                              </FormField>
                              <FormField label="Output layer">
                                <select value={targetLayer} onChange={(event) => setTargetLayer(event.target.value as Exclude<Layer, "BRONZE">)} className={inputClass}>
                                  <option value="SILVER">Silver</option><option value="GOLD">Gold</option>
                                </select>
                              </FormField>
                              <FormField label="Transformation">
                                <select value={operation} onChange={(event) => setOperation(event.target.value as TransformType)} className={inputClass}>
                                  {Object.entries(transformLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                                </select>
                              </FormField>
                              {["drop", "select", "sort", "deduplicate"].includes(operation) && (
                                <FormField label={operation === "deduplicate" ? "Columns (optional)" : "Columns (comma-separated)"}>
                                  <input value={columnText} onChange={(event) => setColumnText(event.target.value)} placeholder={operation === "deduplicate" ? "Leave empty to compare full rows" : "column_a, column_b"} className={inputClass} />
                                </FormField>
                              )}
                              {["rename", "cast", "filter", "fill_null", "calculated"].includes(operation) && (
                                <FormField label={operation === "calculated" ? "Source column" : "Column"}>
                                  <select value={sourceColumn} onChange={(event) => setSourceColumn(event.target.value)} className={inputClass}>
                                    <option value="">Choose a column</option>{columns.map((column) => <option key={column.name} value={column.name}>{column.name} · {column.type}</option>)}
                                  </select>
                                </FormField>
                              )}
                              {operation === "rename" && <FormField label="New column name"><input value={newColumnName} onChange={(event) => setNewColumnName(event.target.value)} className={inputClass} /></FormField>}
                              {operation === "cast" && <FormField label="Target type"><select value={castType} onChange={(event) => setCastType(event.target.value)} className={inputClass}>{["string", "int", "float", "boolean", "date", "datetime"].map((item) => <option key={item} value={item}>{item}</option>)}</select></FormField>}
                              {operation === "filter" && <>
                                <FormField label="Condition"><select value={filterOperator} onChange={(event) => setFilterOperator(event.target.value)} className={inputClass}>{[["eq", "equals"], ["neq", "does not equal"], ["gt", "greater than"], ["gte", "at least"], ["lt", "less than"], ["lte", "at most"], ["contains", "contains"]].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></FormField>
                                <FormField label="Value"><input value={filterValue} onChange={(event) => setFilterValue(event.target.value)} className={inputClass} /></FormField>
                              </>}
                              {operation === "fill_null" && <FormField label="Replacement value"><input value={fillValue} onChange={(event) => setFillValue(event.target.value)} className={inputClass} /></FormField>}
                              {operation === "calculated" && <>
                                <FormField label="New column name"><input value={calculatedName} onChange={(event) => setCalculatedName(event.target.value)} className={inputClass} /></FormField>
                                <FormField label="Operation"><select value={calculatedOperator} onChange={(event) => setCalculatedOperator(event.target.value)} className={inputClass}>{[["add", "Add"], ["subtract", "Subtract"], ["multiply", "Multiply"], ["divide", "Divide"]].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></FormField>
                                <FormField label="Numeric operand"><input type="number" step="any" value={calculatedOperand} onChange={(event) => setCalculatedOperand(event.target.value)} className={inputClass} /></FormField>
                              </>}
                              {operation === "sort" && <label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" checked={sortDescending} onChange={(event) => setSortDescending(event.target.checked)} /> Descending</label>}
                            </div>
                            {operation === "normalize_names" && <p className="rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-3 text-xs text-[var(--muted)]">Trims names, converts them to lowercase, and replaces spaces and hyphens with underscores.</p>}
                            <div className="flex justify-end border-t border-[var(--border)] pt-4">
                              <button disabled={actionLoading || versions.every((version) => version.status !== "COMPLETED")} onClick={() => void submitTransform()} className="flex h-10 items-center gap-2 rounded-lg bg-[var(--accent)] px-4 text-sm font-medium text-[var(--accent-foreground)] disabled:opacity-50">
                                {actionLoading ? <RefreshCw size={15} className="animate-spin" /> : <Zap size={15} />} Run transformation
                              </button>
                            </div>
                          </div>
                        ) : <EmptyState title="Read-only access" detail="Your workspace role does not allow creating transformed versions." />
                      )}
                    </>
                  )}
                </div>
              </>
            )}
          </section>
        </div>
      </div>

      {confirmAction && (
        <div className="fixed inset-0 z-[70] grid place-items-center bg-black/60 px-4" role="presentation">
          <section role="dialog" aria-modal="true" aria-labelledby="confirm-title" className="w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div><h3 id="confirm-title" className="font-semibold">{confirmAction.kind === "restore" ? "Restore a previous version?" : `Promote to ${confirmAction.targetLayer.toLowerCase()}?`}</h3>
                <p className="mt-2 text-sm text-[var(--muted)]">{confirmAction.kind === "restore" ? `Version ${confirmAction.sourceVersion.version_number} will be copied into ${confirmAction.targetLayer} as a new version. Existing versions are not overwritten.` : `The selected version will be written as a new ${confirmAction.targetLayer} version. This operation does not modify the source version.`}</p>
              </div>
              <button onClick={() => setConfirmAction(null)} aria-label="Close confirmation" className="grid size-8 shrink-0 place-items-center rounded-md text-[var(--muted)] hover:bg-[var(--surface-hover)]"><X size={15} /></button>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button disabled={actionLoading} onClick={() => setConfirmAction(null)} className="h-9 rounded-lg border border-[var(--border)] px-3 text-sm">Cancel</button>
              <button disabled={actionLoading} onClick={() => void confirmVersionAction()} className="flex h-9 items-center gap-2 rounded-lg bg-[var(--accent)] px-3 text-sm font-medium text-[var(--accent-foreground)] disabled:opacity-50">
                {actionLoading ? <RefreshCw size={14} className="animate-spin" /> : <Check size={14} />} Confirm
              </button>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}

const inputClass = "h-10 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-3 text-sm outline-none focus:border-[var(--accent)]";

function SummaryCard({ icon: Icon, label, value, detail }: { icon: typeof Database; label: string; value: string; detail: string }) {
  return <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex items-center justify-between"><span className="text-xs text-[var(--muted)]">{label}</span><Icon size={15} className="text-[var(--accent)]" /></div><p className="mt-3 text-2xl font-semibold tracking-tight">{value}</p><p className="mt-1 text-xs text-[var(--muted)]">{detail}</p></div>;
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-3"><p className="text-xs text-[var(--muted)]">{label}</p><p className="mt-2 truncate text-lg font-semibold">{value}</p><p className="mt-1 truncate text-[11px] text-[var(--muted)]">{detail}</p></div>;
}

function Panel({ title, icon: Icon, children }: { title: string; icon: typeof Database; children: React.ReactNode }) {
  return <section className="rounded-lg border border-[var(--border)] p-4"><h4 className="mb-3 flex items-center gap-2 text-sm font-semibold"><Icon size={15} className="text-[var(--accent)]" />{title}</h4>{children}</section>;
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return <div className="flex items-start justify-between gap-4 border-b border-[var(--border)] py-2.5 last:border-0"><span className="text-xs text-[var(--muted)]">{label}</span><span className="max-w-[65%] break-words text-right text-xs font-medium">{value}</span></div>;
}

function LayerBadge({ layer }: { layer: Layer }) {
  return <span className="rounded-full border px-2 py-1 text-[10px] font-medium" style={{ borderColor: `color-mix(in srgb, ${layerColor(layer)} 40%, transparent)`, color: layerColor(layer) }}>{layer}</span>;
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="grid min-h-[240px] place-items-center p-8 text-center"><div><div className="mx-auto grid size-11 place-items-center rounded-xl border border-[var(--border)] bg-[var(--surface-raised)] text-[var(--muted)]"><Table2 size={18} /></div><p className="mt-3 text-sm font-medium">{title}</p><p className="mx-auto mt-1 max-w-md text-xs leading-5 text-[var(--muted)]">{detail}</p></div></div>;
}

function Notice({ kind, message, onDismiss }: { kind: "success" | "error"; message: string; onDismiss?: () => void }) {
  const color = kind === "success" ? "var(--success)" : "var(--danger)";
  return <div className="mt-4 flex items-start justify-between gap-3 rounded-lg border px-3 py-2.5 text-sm" style={{ borderColor: `color-mix(in srgb, ${color} 35%, transparent)`, background: `color-mix(in srgb, ${color} 8%, var(--surface))` }}><span style={{ color }}>{message}</span>{onDismiss && <button onClick={onDismiss} aria-label="Dismiss message" className="text-[var(--muted)]"><X size={14} /></button>}</div>;
}

function InlineLoading() {
  return <div className="flex items-center gap-2 py-6 text-sm text-[var(--muted)]"><RefreshCw size={14} className="animate-spin" />Loading data...</div>;
}

function LoadingDetails() {
  return <div className="space-y-3">{[0, 1, 2, 3].map((item) => <div key={item} className="h-14 animate-pulse rounded-lg bg-[var(--surface-raised)]" />)}</div>;
}

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block space-y-1.5"><span className="text-xs font-medium text-[var(--muted)]">{label}</span>{children}</label>;
}

function PreviewTable({ preview }: { preview: Preview }) {
  return (
    <div className="max-h-[520px] overflow-auto rounded-lg border border-[var(--border)]">
      <table className="min-w-full text-left text-xs">
        <thead className="sticky top-0 bg-[var(--surface-raised)]"><tr>{preview.columns.map((column) => <th key={column.name} className="whitespace-nowrap border-b border-[var(--border)] px-3 py-2.5 font-medium">{column.name}<span className="ml-2 font-normal text-[var(--muted)]">{column.type}</span></th>)}</tr></thead>
        <tbody className="divide-y divide-[var(--border)]">{preview.rows.map((row, index) => <tr key={index}>{preview.columns.map((column) => <td key={column.name} className="max-w-64 whitespace-nowrap px-3 py-2 text-[var(--foreground)]">{row[column.name] === null || row[column.name] === undefined ? <span className="text-[var(--muted)]">null</span> : prettyValue(row[column.name])}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}
