"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  FormEvent,
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
} from "react";
import dynamic from "next/dynamic";
import {
  AlertCircle,
  Check,
  ChevronDown,
  Clock3,
  Database,
  FileClock,
  History,
  Layers3,
  LoaderCircle,
  Play,
  Plus,
  Save,
  Search,
  Table2,
  Trash2,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { useTheme } from "@/components/theme-provider";

const Editor = dynamic(() => import("@monaco-editor/react"), { ssr: false });

type Layer = "BRONZE" | "SILVER" | "GOLD";
type Role = "OWNER" | "ADMIN" | "EDITOR" | "VIEWER";
type ExplorerPanel = "catalog" | "saved" | "history";
type CatalogColumn = { name: string; type?: string; data_type?: string };
type CatalogTable = {
  name: string;
  display_name: string;
  layer: Layer;
  version: number;
  row_count?: number | null;
  column_count?: number | null;
  columns: CatalogColumn[];
};
type SqlResult = {
  id: string;
  status: "SUCCESS";
  duration_ms: number;
  columns: { name: string; type: string }[];
  rows: Record<string, unknown>[];
  returned_rows: number;
  total_rows_available: number;
  truncated: boolean;
  error: string | null;
};
type HistoryItem = {
  id: string;
  query_name: string | null;
  sql_text: string;
  execution_status: "SUCCESS" | "FAILED" | "RUNNING";
  execution_duration_ms: number | null;
  rows_returned: number | null;
  error_message: string | null;
  created_at: string;
};
type SavedQuery = {
  id: string;
  name: string;
  description: string | null;
  sql_text: string;
};
type SaveDraft = { id: string | null; name: string; description: string };
type DeleteTarget = { kind: "saved" | "history"; id: string; label: string };
type DragOrigin = { pointerId: number; y: number; height: number };

const initialSql = "-- Select a table from the workspace catalog\nSELECT 1 AS value";
const layerStyles: Record<Layer, string> = {
  BRONZE: "text-[var(--layer-bronze)] border-[color-mix(in_srgb,var(--layer-bronze)_35%,transparent)] bg-[color-mix(in_srgb,var(--layer-bronze)_8%,transparent)]",
  SILVER: "text-[var(--layer-silver)] border-[color-mix(in_srgb,var(--layer-silver)_35%,transparent)] bg-[color-mix(in_srgb,var(--layer-silver)_8%,transparent)]",
  GOLD: "text-[var(--layer-gold)] border-[color-mix(in_srgb,var(--layer-gold)_35%,transparent)] bg-[color-mix(in_srgb,var(--layer-gold)_8%,transparent)]",
};

function quoteIdentifier(identifier: string) {
  return `"${identifier.replaceAll('"', '""')}"`;
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown time" : date.toLocaleString();
}

function formatCell(value: unknown) {
  if (value === null || value === undefined) return "NULL";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function csvCell(value: unknown) {
  let text = value === null || value === undefined
    ? ""
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);
  if (typeof value === "string" && /^[\t\r=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

export default function SqlWorkspacePage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = use(params);
  const { user } = useAuth();
  const { theme } = useTheme();
  const [catalog, setCatalog] = useState<CatalogTable[]>([]);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [saved, setSaved] = useState<SavedQuery[]>([]);
  const [role, setRole] = useState<Role | null>(null);
  const [sql, setSql] = useState(initialSql);
  const [result, setResult] = useState<SqlResult | null>(null);
  const [selectedSavedId, setSelectedSavedId] = useState<string | null>(null);
  const [panel, setPanel] = useState<ExplorerPanel>("catalog");
  const [search, setSearch] = useState("");
  const [layerFilter, setLayerFilter] = useState<Layer | "ALL">("ALL");
  const [historyFilter, setHistoryFilter] = useState<"ALL" | HistoryItem["execution_status"]>("ALL");
  const [workspaceLoading, setWorkspaceLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [queryError, setQueryError] = useState("");
  const [actionError, setActionError] = useState("");
  const [saveDraft, setSaveDraft] = useState<SaveDraft | null>(null);
  const [saveError, setSaveError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [editorHeight, setEditorHeight] = useState(400);
  const editorInsertRef = useRef<((text: string) => void) | null>(null);
  const executeRef = useRef<() => Promise<void>>(async () => {});
  const openSaveDialogRef = useRef<(saveAsNew?: boolean, query?: SavedQuery) => void>(() => {});
  const dragOriginRef = useRef<DragOrigin | null>(null);

  const selectedSaved = useMemo(
    () => saved.find((item) => item.id === selectedSavedId) ?? null,
    [saved, selectedSavedId],
  );
  const canManageSaved = role === "OWNER" || role === "ADMIN" || role === "EDITOR";
  const filteredCatalog = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return catalog.filter((table) =>
      (layerFilter === "ALL" || table.layer === layerFilter) &&
      (!needle || table.display_name.toLowerCase().includes(needle) ||
        table.name.toLowerCase().includes(needle) ||
        table.columns.some((column) => column.name.toLowerCase().includes(needle))),
    );
  }, [catalog, layerFilter, search]);
  const filteredSaved = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return saved.filter((item) =>
      !needle || item.name.toLowerCase().includes(needle) ||
      item.sql_text.toLowerCase().includes(needle) ||
      (item.description ?? "").toLowerCase().includes(needle),
    );
  }, [saved, search]);
  const filteredHistory = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return history.filter((item) =>
      (historyFilter === "ALL" || item.execution_status === historyFilter) &&
      (!needle || item.sql_text.toLowerCase().includes(needle) ||
        (item.query_name ?? "").toLowerCase().includes(needle)),
    );
  }, [history, historyFilter, search]);

  const load = useCallback(async () => {
    setWorkspaceLoading(true);
    setLoadError("");
    try {
      const [catalogResult, historyResult, savedResult, membersResult] = await Promise.all([
        api<{ items: CatalogTable[] }>(`/api/v1/workspaces/${workspaceId}/sql/catalog`),
        api<HistoryItem[]>(`/api/v1/workspaces/${workspaceId}/sql/history?page=1&page_size=100`),
        api<SavedQuery[]>(`/api/v1/workspaces/${workspaceId}/sql/saved`),
        api<{ user_id: string; role: Role }[]>(`/api/v1/workspaces/${workspaceId}/members`),
      ]);
      const errors = [
        catalogResult.error && `Catalog: ${catalogResult.error}`,
        historyResult.error && `History: ${historyResult.error}`,
        savedResult.error && `Saved queries: ${savedResult.error}`,
        membersResult.error && `Permissions: ${membersResult.error}`,
      ].filter((message): message is string => Boolean(message));
      setLoadError(errors.join(" "));
      setCatalog(catalogResult.data?.items ?? []);
      setHistory(historyResult.data ?? []);
      setSaved(savedResult.data ?? []);
      setRole(membersResult.data?.find((member) => member.user_id === user?.id)?.role ?? null);
    } catch {
      setLoadError("Unable to load this workspace's SQL tools. Check your connection and try again.");
      setCatalog([]);
      setHistory([]);
      setSaved([]);
      setRole(null);
    } finally {
      setWorkspaceLoading(false);
    }
  }, [user?.id, workspaceId]);

  useEffect(() => {
    if (!user) return;
    const timeout = window.setTimeout(() => {
      setCatalog([]);
      setHistory([]);
      setSaved([]);
      setRole(null);
      setResult(null);
      setSql(initialSql);
      setSelectedSavedId(null);
      setPanel("catalog");
      setSearch("");
      setLayerFilter("ALL");
      setHistoryFilter("ALL");
      setQueryError("");
      setActionError("");
      setLoadError("");
      setSaveDraft(null);
      setDeleteTarget(null);
      void load();
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [load, user]);

  const openSaveDialog = useCallback((saveAsNew = false, query?: SavedQuery) => {
    if (!canManageSaved) return;
    const target = query ?? (!saveAsNew ? selectedSaved : null);
    setSaveError("");
    setSaveDraft({
      id: target?.id ?? null,
      name: target?.name ?? "",
      description: target?.description ?? "",
    });
  }, [canManageSaved, selectedSaved]);

  const saveQuery = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!saveDraft || !canManageSaved || saving) return;
    const name = saveDraft.name.trim();
    if (!name || !sql.trim()) {
      setSaveError("Enter a query name and SQL before saving.");
      return;
    }
    setSaving(true);
    setSaveError("");
    try {
      const response = saveDraft.id
        ? await api<SavedQuery>(`/api/v1/workspaces/${workspaceId}/sql/saved/${saveDraft.id}`, {
            method: "PATCH",
            body: JSON.stringify({ name, description: saveDraft.description.trim() || null, sql_text: sql }),
          })
        : await api<SavedQuery>(`/api/v1/workspaces/${workspaceId}/sql/saved`, {
            method: "POST",
            body: JSON.stringify({ name, description: saveDraft.description.trim() || null, sql_text: sql }),
          });
      if (response.error || !response.data) {
        setSaveError(response.error ?? "The saved query could not be stored.");
        return;
      }
      setSelectedSavedId(response.data.id);
      setSaveDraft(null);
      setPanel("saved");
      await load();
    } catch {
      setSaveError("Unable to reach the server. Your query has not been saved.");
    } finally {
      setSaving(false);
    }
  };

  const execute = useCallback(async () => {
    if (!sql.trim() || running) return;
    setRunning(true);
    setQueryError("");
    setActionError("");
    setResult(null);
    try {
      const response = await api<SqlResult>(`/api/v1/workspaces/${workspaceId}/sql/execute`, {
        method: "POST",
        body: JSON.stringify({ sql, query_name: selectedSaved?.name ?? null }),
      });
      if (response.error) setQueryError(response.error);
      else if (response.data) setResult(response.data);
      else setQueryError("The SQL service returned no result.");
      await load();
    } catch {
      setQueryError("Unable to reach the SQL service. Check your connection and try again.");
    } finally {
      setRunning(false);
    }
  }, [load, running, selectedSaved, sql, workspaceId]);

  useEffect(() => {
    executeRef.current = execute;
    openSaveDialogRef.current = openSaveDialog;
  }, [execute, openSaveDialog]);

  const requestDelete = (kind: DeleteTarget["kind"], id: string, label: string) => {
    setActionError("");
    setDeleteTarget({ kind, id, label });
  };

  const confirmDelete = async () => {
    if (!deleteTarget || deleting) return;
    setDeleting(true);
    setActionError("");
    const endpoint = deleteTarget.kind === "saved"
      ? `/api/v1/workspaces/${workspaceId}/sql/saved/${deleteTarget.id}`
      : `/api/v1/workspaces/${workspaceId}/sql/history/${deleteTarget.id}`;
    try {
      const response = await api<never>(endpoint, { method: "DELETE" });
      if (response.error) {
        setActionError(response.error);
        setDeleteTarget(null);
        return;
      }
      if (deleteTarget.kind === "saved" && selectedSavedId === deleteTarget.id) {
        setSelectedSavedId(null);
      }
      setDeleteTarget(null);
      await load();
    } catch {
      setActionError("Unable to reach the server. Nothing was deleted.");
      setDeleteTarget(null);
    } finally {
      setDeleting(false);
    }
  };

  const exportCsv = () => {
    if (!result) return;
    const lines = [
      result.columns.map((column) => csvCell(column.name)).join(","),
      ...result.rows.map((row) =>
        result.columns.map((column) => csvCell(row[column.name])).join(","),
      ),
    ];
    const url = URL.createObjectURL(new Blob(["\uFEFF", lines.join("\r\n")], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "pylake-query-results.csv";
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  const insertAtCursor = (text: string) => {
    editorInsertRef.current?.(text);
  };

  const onDividerPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    dragOriginRef.current = { pointerId: event.pointerId, y: event.clientY, height: editorHeight };
  };
  const onDividerPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const origin = dragOriginRef.current;
    if (!origin || origin.pointerId !== event.pointerId) return;
    setEditorHeight(Math.max(240, Math.min(720, origin.height + event.clientY - origin.y)));
  };
  const onDividerPointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (dragOriginRef.current?.pointerId === event.pointerId) dragOriginRef.current = null;
  };
  const onDividerKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      event.preventDefault();
      const adjustment = event.key === "ArrowUp" ? 24 : -24;
      setEditorHeight((height) => Math.max(240, Math.min(720, height + adjustment)));
    }
  };

  const panelTabs: { id: ExplorerPanel; label: string; icon: typeof Database }[] = [
    { id: "catalog", label: "Catalog", icon: Database },
    { id: "saved", label: "Saved", icon: Save },
    { id: "history", label: "History", icon: History },
  ];

  return (
    <main className="min-h-[calc(100vh-64px)] px-3 py-4 md:px-5 md:py-5">
      <div className="mx-auto max-w-[1900px]">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <Link href={`/workspaces/${workspaceId}`} className="text-xs text-[var(--muted)] transition-colors hover:text-[var(--accent)]">
              Workspace / Overview
            </Link>
            <p className="mt-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--accent)]">Query Studio</p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight md:text-3xl">SQL Workspace</h1>
          </div>
          <div className="flex items-center gap-2">
            {role && <span className="rounded-full border border-[var(--border)] px-2.5 py-1 text-[10px] font-medium text-[var(--muted)]">{role}</span>}
            <span className="rounded-full border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted)]">DuckDB · read-only</span>
          </div>
        </div>

        {(loadError || actionError) && (
          <div role="alert" className="mt-4 flex items-start gap-2 rounded-lg border border-[color-mix(in_srgb,var(--danger)_35%,transparent)] bg-[color-mix(in_srgb,var(--danger)_8%,var(--surface))] px-4 py-3 text-sm text-[var(--danger)]">
            <AlertCircle size={16} className="mt-0.5 shrink-0" />
            <p>{[loadError, actionError].filter(Boolean).join(" ")}</p>
          </div>
        )}

        <div className="mt-5 grid min-h-[680px] gap-3 lg:grid-cols-[290px_minmax(0,1fr)]">
          <aside className="flex min-h-[420px] min-w-0 flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-soft)] lg:min-h-0">
            <div className="border-b border-[var(--border)] p-3">
              <label className="relative block">
                <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)]" />
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder={panel === "catalog" ? "Search tables and columns" : panel === "saved" ? "Search saved queries" : "Search query history"}
                  aria-label={`Search ${panel}`}
                  className="h-10 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] pl-9 pr-3 text-xs outline-none transition-colors placeholder:text-[var(--muted)] focus:border-[var(--accent)]"
                />
              </label>
              <div className="mt-3 grid grid-cols-3 gap-1 rounded-lg bg-[var(--surface-raised)] p-1" role="group" aria-label="SQL explorer">
                {panelTabs.map(({ id, label, icon: Icon }) => (
                  <button
                    key={id}
                    type="button"
                    aria-pressed={panel === id}
                    onClick={() => setPanel(id)}
                    className={`flex h-8 items-center justify-center gap-1.5 rounded-md text-[11px] font-medium transition-colors ${panel === id ? "bg-[var(--surface)] text-[var(--foreground)] shadow-sm" : "text-[var(--muted)] hover:text-[var(--foreground)]"}`}
                  >
                    <Icon size={13} />
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              {panel === "catalog" && (
                <>
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">Queryable tables</p>
                    <select
                      value={layerFilter}
                      onChange={(event) => setLayerFilter(event.target.value as Layer | "ALL")}
                      aria-label="Filter tables by layer"
                      className="h-7 rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 text-[10px] text-[var(--muted)] outline-none focus:border-[var(--accent)]"
                    >
                      <option value="ALL">All layers</option>
                      <option value="BRONZE">Bronze</option>
                      <option value="SILVER">Silver</option>
                      <option value="GOLD">Gold</option>
                    </select>
                  </div>
                  {workspaceLoading ? (
                    <div className="space-y-2" aria-label="Loading catalog">
                      {[0, 1, 2, 3].map((item) => <div key={item} className="h-14 animate-pulse rounded-lg bg-[var(--surface-raised)]" />)}
                    </div>
                  ) : filteredCatalog.length === 0 ? (
                    <div className="rounded-lg border border-dashed border-[var(--border-strong)] px-3 py-6 text-center">
                      <Database size={18} className="mx-auto text-[var(--muted)]" />
                      <p className="mt-2 text-xs font-medium">{catalog.length ? "No matching tables" : "No queryable tables yet"}</p>
                      <p className="mt-1 text-[11px] leading-5 text-[var(--muted)]">
                        {catalog.length ? "Try another search or layer." : "Promote a completed Parquet version to Silver or Gold to query it."}
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {filteredCatalog.map((table) => (
                        <details key={table.name} className="group rounded-lg border border-[var(--border)] bg-[var(--surface)] transition-colors open:border-[var(--border-strong)] open:bg-[var(--surface-raised)]">
                          <summary className="flex cursor-pointer list-none items-center gap-2 px-2.5 py-2.5 [&::-webkit-details-marker]:hidden">
                            <ChevronDown size={13} className="shrink-0 text-[var(--muted)] transition-transform group-open:rotate-180" />
                            <Table2 size={14} className="shrink-0 text-[var(--muted)]" />
                            <span className="min-w-0 flex-1 truncate text-xs font-medium" title={table.display_name}>{table.display_name}</span>
                            <span className={`rounded border px-1.5 py-0.5 text-[9px] font-semibold ${layerStyles[table.layer]}`}>{table.layer}</span>
                          </summary>
                          <div className="border-t border-[var(--border)] px-2.5 pb-2.5 pt-2">
                            <div className="flex items-center justify-between gap-2 text-[10px] text-[var(--muted)]">
                              <span>v{table.version}{table.row_count != null ? ` · ${table.row_count.toLocaleString()} rows` : ""}</span>
                              <button
                                type="button"
                                onClick={() => {
                                  setSql(`SELECT *\nFROM ${quoteIdentifier(table.name)}\nLIMIT 100`);
                                  setSelectedSavedId(null);
                                }}
                                className="font-medium text-[var(--accent)] transition-colors hover:text-[var(--accent-strong)]"
                              >
                                Preview
                              </button>
                            </div>
                            <button
                              type="button"
                              onClick={() => insertAtCursor(quoteIdentifier(table.name))}
                              className="mt-2 flex w-full items-center gap-1.5 rounded px-1 py-1 text-left font-mono text-[11px] text-[var(--foreground)] transition-colors hover:bg-[var(--surface-hover)]"
                              title="Insert table name at cursor"
                            >
                              <Plus size={12} className="text-[var(--accent)]" /> {table.name}
                            </button>
                            <div className="mt-1 space-y-0.5">
                              {table.columns.map((column) => (
                                <button
                                  key={`${table.name}.${column.name}`}
                                  type="button"
                                  onClick={() => insertAtCursor(`${quoteIdentifier(table.name)}.${quoteIdentifier(column.name)}`)}
                                  className="flex w-full items-center justify-between gap-2 rounded px-1 py-1 text-left font-mono text-[10px] text-[var(--muted)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--foreground)]"
                                  title={`Insert ${table.display_name}.${column.name} at cursor`}
                                >
                                  <span className="flex min-w-0 items-center gap-1.5 truncate"><Plus size={10} className="shrink-0 text-[var(--accent)]" />{column.name}</span>
                                  <span className="shrink-0">{column.type ?? column.data_type ?? "unknown"}</span>
                                </button>
                              ))}
                            </div>
                          </div>
                        </details>
                      ))}
                    </div>
                  )}
                  <div className="mt-4 flex items-start gap-2 rounded-lg bg-[var(--surface-raised)] p-2.5 text-[10px] leading-4 text-[var(--muted)]">
                    <Layers3 size={13} className="mt-0.5 shrink-0 text-[var(--accent)]" />
                    Only completed, queryable workspace tables are listed.
                  </div>
                </>
              )}

              {panel === "saved" && (
                <>
                  <div className="mb-3 flex items-center justify-between">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">Saved queries</p>
                    <span className="text-[10px] text-[var(--muted)]">{filteredSaved.length}</span>
                  </div>
                  {!canManageSaved && role === "VIEWER" && (
                    <p className="mb-3 rounded-lg bg-[var(--surface-raised)] p-2.5 text-[10px] leading-4 text-[var(--muted)]">Viewer access is read-only. You can load saved queries but cannot change them.</p>
                  )}
                  {workspaceLoading ? (
                    <div className="space-y-2" aria-label="Loading saved queries">{[0, 1, 2].map((item) => <div key={item} className="h-16 animate-pulse rounded-lg bg-[var(--surface-raised)]" />)}</div>
                  ) : filteredSaved.length === 0 ? (
                    <p className="rounded-lg border border-dashed border-[var(--border-strong)] px-3 py-6 text-center text-xs text-[var(--muted)]">
                      {saved.length ? "No saved queries match your search." : "Save a query to keep it available in this workspace."}
                    </p>
                  ) : (
                    <div className="space-y-2">
                      {filteredSaved.map((item) => (
                        <div key={item.id} className={`rounded-lg border p-2.5 transition-colors ${selectedSavedId === item.id ? "border-[var(--accent)] bg-[var(--accent-soft)]" : "border-[var(--border)] hover:bg-[var(--surface-raised)]"}`}>
                          <button
                            type="button"
                            onClick={() => { setSql(item.sql_text); setSelectedSavedId(item.id); }}
                            className="block w-full text-left"
                          >
                            <span className="block truncate text-xs font-medium">{item.name}</span>
                            {item.description && <span className="mt-1 block truncate text-[10px] text-[var(--muted)]">{item.description}</span>}
                            <span className="mt-2 block max-h-8 overflow-hidden font-mono text-[9px] leading-4 text-[var(--muted)]">{item.sql_text}</span>
                          </button>
                          <div className="mt-2 flex items-center justify-end gap-1 border-t border-[var(--border)] pt-2">
                            <button type="button" onClick={() => { setSql(item.sql_text); setSelectedSavedId(item.id); openSaveDialog(false, item); }} disabled={!canManageSaved} className="rounded px-2 py-1 text-[10px] text-[var(--muted)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--foreground)] disabled:opacity-40">Edit details</button>
                            <button type="button" aria-label={`Delete saved query ${item.name}`} onClick={() => requestDelete("saved", item.id, item.name)} disabled={!canManageSaved} className="rounded p-1.5 text-[var(--muted)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--danger)] disabled:opacity-40"><Trash2 size={13} /></button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}

              {panel === "history" && (
                <>
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">Your recent runs</p>
                    <select
                      value={historyFilter}
                      onChange={(event) => setHistoryFilter(event.target.value as typeof historyFilter)}
                      aria-label="Filter query history by status"
                      className="h-7 rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 text-[10px] text-[var(--muted)] outline-none focus:border-[var(--accent)]"
                    >
                      <option value="ALL">All status</option>
                      <option value="SUCCESS">Succeeded</option>
                      <option value="FAILED">Failed</option>
                      <option value="RUNNING">Running</option>
                    </select>
                  </div>
                  {workspaceLoading ? (
                    <div className="space-y-2" aria-label="Loading query history">{[0, 1, 2].map((item) => <div key={item} className="h-16 animate-pulse rounded-lg bg-[var(--surface-raised)]" />)}</div>
                  ) : filteredHistory.length === 0 ? (
                    <p className="rounded-lg border border-dashed border-[var(--border-strong)] px-3 py-6 text-center text-xs text-[var(--muted)]">
                      {history.length ? "No history entries match your filters." : "Queries you run will appear here."}
                    </p>
                  ) : (
                    <div className="space-y-1">
                      {filteredHistory.map((item) => (
                        <div key={item.id} className="group rounded-lg border border-transparent p-2 transition-colors hover:border-[var(--border)] hover:bg-[var(--surface-raised)]">
                          <button
                            type="button"
                            onClick={() => { setSql(item.sql_text); setSelectedSavedId(null); }}
                            className="block w-full text-left"
                          >
                            <span className="flex items-center gap-1.5 text-[10px]">
                              <span className={`h-1.5 w-1.5 rounded-full ${item.execution_status === "SUCCESS" ? "bg-[var(--success)]" : item.execution_status === "FAILED" ? "bg-[var(--danger)]" : "bg-[var(--warning)]"}`} />
                              <span className="font-medium">{item.query_name || item.execution_status}</span>
                              <span className="ml-auto text-[9px] text-[var(--muted)]">{item.execution_duration_ms ?? "—"} ms</span>
                            </span>
                            <span className="mt-1.5 block max-h-9 overflow-hidden break-all font-mono text-[9px] leading-4 text-[var(--muted)]">{item.sql_text}</span>
                            <span className="mt-1.5 flex items-center gap-1 text-[9px] text-[var(--muted)]"><Clock3 size={10} />{formatDate(item.created_at)}</span>
                            {item.execution_status === "FAILED" && item.error_message && <span className="mt-1 block line-clamp-2 text-[9px] text-[var(--danger)]">{item.error_message}</span>}
                          </button>
                          <button type="button" aria-label="Delete query history entry" onClick={() => requestDelete("history", item.id, item.query_name || "this history entry")} className="mt-1 hidden rounded px-1.5 py-1 text-[9px] text-[var(--muted)] transition-colors hover:text-[var(--danger)] group-hover:inline-flex focus:inline-flex">
                            <Trash2 size={11} /> Delete
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                  {history.length >= 100 && <p className="mt-3 text-[9px] leading-4 text-[var(--muted)]">Showing the latest 100 runs.</p>}
                </>
              )}
            </div>
          </aside>

          <section className="grid min-w-0 content-start gap-3">
            <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-soft)]">
              <div className="flex min-h-12 flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] px-3 py-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[var(--accent-soft)] text-[var(--accent)]"><Database size={14} /></span>
                  <div className="min-w-0">
                    <p className="truncate text-xs font-medium">{selectedSaved?.name ?? "Untitled query"}</p>
                    <p className="text-[9px] text-[var(--muted)]">{selectedSaved ? "Saved query" : "SQL editor"} · Ctrl/Cmd + Enter to run</p>
                  </div>
                  {selectedSaved && sql !== selectedSaved.sql_text && <span className="rounded-full bg-[var(--surface-raised)] px-2 py-1 text-[9px] text-[var(--warning)]">Modified</span>}
                </div>
                <div className="flex items-center gap-1.5">
                  {canManageSaved ? (
                    <>
                      <button type="button" onClick={() => openSaveDialog(false)} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[var(--border-strong)] px-2.5 text-[11px] font-medium transition-colors hover:bg-[var(--surface-hover)]">
                        <Save size={13} /> {selectedSaved ? "Save changes" : "Save"}
                      </button>
                      <button type="button" onClick={() => openSaveDialog(true)} className="hidden h-8 items-center gap-1 rounded-lg px-2 text-[11px] text-[var(--muted)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--foreground)] sm:inline-flex">
                        <Plus size={13} /> Save as
                      </button>
                    </>
                  ) : (
                    <span className="hidden text-[10px] text-[var(--muted)] sm:inline">Read-only query access</span>
                  )}
                  <button
                    type="button"
                    onClick={() => void execute()}
                    disabled={running || !sql.trim()}
                    className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 text-[11px] font-semibold text-[var(--accent-foreground)] transition-colors hover:bg-[var(--accent-strong)] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {running ? <LoaderCircle size={13} className="animate-spin" /> : <Play size={13} fill="currentColor" />}
                    {running ? "Running" : "Run"}
                  </button>
                </div>
              </div>
              <Editor
                height={`${editorHeight}px`}
                defaultLanguage="sql"
                language="sql"
                theme={theme === "dark" ? "vs-dark" : "light"}
                value={sql}
                onChange={(value) => setSql(value ?? "")}
                onMount={(editor, monaco) => {
                  editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => { void executeRef.current(); });
                  editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => openSaveDialogRef.current(false));
                  editorInsertRef.current = (text) => {
                    const selection = editor.getSelection();
                    if (selection) editor.executeEdits("pylake-catalog-insert", [{ range: selection, text, forceMoveMarkers: true }]);
                    editor.focus();
                  };
                }}
                options={{
                  minimap: { enabled: false },
                  fontSize: 13,
                  lineNumbers: "on",
                  folding: true,
                  scrollBeyondLastLine: false,
                  automaticLayout: true,
                  tabSize: 2,
                  wordWrap: "off",
                  renderLineHighlight: "line",
                  padding: { top: 14, bottom: 14 },
                  smoothScrolling: true,
                  bracketPairColorization: { enabled: true },
                  suggestOnTriggerCharacters: true,
                  quickSuggestions: true,
                }}
              />
              <div
                role="separator"
                aria-label="Resize SQL editor and results"
                aria-orientation="horizontal"
                aria-valuemin={240}
                aria-valuemax={720}
                aria-valuenow={editorHeight}
                tabIndex={0}
                onPointerDown={onDividerPointerDown}
                onPointerMove={onDividerPointerMove}
                onPointerUp={onDividerPointerUp}
                onPointerCancel={onDividerPointerUp}
                onKeyDown={onDividerKeyDown}
                className="group flex h-3 cursor-row-resize touch-none items-center justify-center border-t border-[var(--border)] bg-[var(--surface-raised)] outline-none transition-colors hover:bg-[var(--surface-hover)] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--accent)]"
                title="Drag to resize, or use the arrow keys"
              >
                <span className="h-0.5 w-10 rounded-full bg-[var(--border-strong)] transition-colors group-hover:bg-[var(--accent)]" />
              </div>
              <div className="flex min-h-8 items-center justify-between gap-2 border-t border-[var(--border)] px-3 text-[9px] text-[var(--muted)]">
                <span className="flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-[var(--success)]" /> Workspace catalog · server-side read-only validation</span>
                <span>{sql.length.toLocaleString()} characters</span>
              </div>
            </div>

            <section className="min-h-[280px] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
              <div className="flex min-h-12 flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] px-4 py-2">
                <div className="flex items-center gap-2">
                  <Table2 size={14} className="text-[var(--muted)]" />
                  <h2 className="text-xs font-semibold">Results</h2>
                  {result && <span className="rounded-full border border-[var(--border)] px-2 py-0.5 text-[9px] text-[var(--muted)]">{result.returned_rows.toLocaleString()} returned</span>}
                </div>
                <div className="flex items-center gap-2 text-[10px] text-[var(--muted)]">
                  {result && <><span>{result.duration_ms} ms</span><span className="text-[var(--border-strong)]">·</span><span>{result.columns.length} columns</span></>}
                  {result && (
                    <button type="button" onClick={exportCsv} disabled={result.columns.length === 0} className="ml-1 inline-flex h-7 items-center gap-1.5 rounded-md border border-[var(--border-strong)] px-2 text-[10px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--surface-hover)] disabled:opacity-50">
                      <FileClock size={12} /> Export CSV
                    </button>
                  )}
                </div>
              </div>
              {queryError ? (
                <div role="alert" className="m-4 flex gap-2 rounded-lg border border-[color-mix(in_srgb,var(--danger)_35%,transparent)] bg-[color-mix(in_srgb,var(--danger)_8%,var(--surface))] p-3 text-xs text-[var(--danger)]">
                  <AlertCircle size={15} className="mt-0.5 shrink-0" />
                  <div><p className="font-semibold">Query failed</p><p className="mt-1 break-words leading-5">{queryError}</p></div>
                </div>
              ) : running ? (
                <div className="flex min-h-[220px] flex-col items-center justify-center text-center">
                  <LoaderCircle size={20} className="animate-spin text-[var(--accent)]" />
                  <p className="mt-3 text-xs font-medium">Executing query</p>
                  <p className="mt-1 text-[10px] text-[var(--muted)]">The workspace SQL service enforces read-only rules and result limits.</p>
                </div>
              ) : result ? (
                <>
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-[var(--border)] px-4 py-2 text-[10px] text-[var(--muted)]">
                    <span><Check size={11} className="mr-1 inline text-[var(--success)]" />Completed</span>
                    <span>{result.total_rows_available.toLocaleString()}{result.truncated ? "+" : ""} rows available</span>
                    {result.truncated && <span className="text-[var(--warning)]">Result capped by server limit</span>}
                  </div>
                  {result.columns.length === 0 ? (
                    <p className="px-4 py-8 text-center text-xs text-[var(--muted)]">The query completed without tabular columns.</p>
                  ) : result.rows.length === 0 ? (
                    <p className="px-4 py-8 text-center text-xs text-[var(--muted)]">Query completed successfully. No rows matched.</p>
                  ) : (
                    <div className="max-h-[460px] overflow-auto">
                      <table className="w-full min-w-[640px] border-collapse text-left text-xs">
                        <thead className="sticky top-0 z-10 bg-[var(--surface-raised)]">
                          <tr>
                            <th className="w-12 border-b border-[var(--border)] px-3 py-2 text-right text-[9px] font-medium text-[var(--muted)]">#</th>
                            {result.columns.map((column, index) => (
                              <th key={`${column.name}-${index}`} className="max-w-64 border-b border-[var(--border)] px-3 py-2 font-medium">
                                <span className="block truncate" title={column.name}>{column.name}</span>
                                <span className="mt-0.5 block text-[9px] font-normal text-[var(--muted)]">{column.type}</span>
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {result.rows.map((row, rowIndex) => (
                            <tr key={rowIndex} className="border-b border-[var(--border)] transition-colors last:border-0 hover:bg-[var(--surface-raised)]">
                              <td className="px-3 py-2 text-right font-mono text-[9px] text-[var(--muted)]">{rowIndex + 1}</td>
                              {result.columns.map((column, columnIndex) => {
                                const value = row[column.name];
                                return (
                                  <td key={`${column.name}-${columnIndex}`} className={`max-w-80 truncate px-3 py-2 font-mono ${value == null ? "italic text-[var(--muted)]" : "text-[var(--foreground)]"}`} title={formatCell(value)}>
                                    {formatCell(value)}
                                  </td>
                                );
                              })}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </>
              ) : (
                <div className="flex min-h-[220px] flex-col items-center justify-center px-4 text-center">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] text-[var(--muted)]"><Table2 size={17} /></div>
                  <p className="mt-3 text-xs font-medium">Results will appear here</p>
                  <p className="mt-1 max-w-sm text-[10px] leading-5 text-[var(--muted)]">Run a query to inspect its bounded result set, execution time, and status.</p>
                </div>
              )}
            </section>

            <div className="flex flex-wrap items-center justify-between gap-2 px-1 text-[9px] text-[var(--muted)]" aria-live="polite">
              <span>{running ? "Query in progress" : result ? `Last run completed in ${result.duration_ms} ms` : "Ready to query"}</span>
              <span>Results are limited by the workspace SQL service.</span>
            </div>
          </section>
        </div>
      </div>

      {saveDraft && (
        <div className="fixed inset-0 z-[80] grid place-items-center bg-black/65 px-4 py-6" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) setSaveDraft(null); }}>
          <form onSubmit={(event) => void saveQuery(event)} onKeyDown={(event) => { if (event.key === "Escape" && !saving) setSaveDraft(null); }} role="dialog" aria-modal="true" aria-labelledby="save-query-title" className="w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 shadow-2xl">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 id="save-query-title" className="text-base font-semibold">{saveDraft.id ? "Update saved query" : "Save query"}</h2>
                <p className="mt-1 text-xs text-[var(--muted)]">Saved queries are private to your account within this workspace.</p>
              </div>
              <button type="button" aria-label="Close dialog" onClick={() => setSaveDraft(null)} disabled={saving} className="rounded-md p-1.5 text-[var(--muted)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--foreground)]"><X size={15} /></button>
            </div>
            <label className="mt-5 block text-xs font-medium">Name
              <input autoFocus maxLength={200} required value={saveDraft.name} onChange={(event) => setSaveDraft({ ...saveDraft, name: event.target.value })} className="mt-1.5 h-10 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-3 text-sm outline-none focus:border-[var(--accent)]" />
            </label>
            <label className="mt-4 block text-xs font-medium">Description <span className="font-normal text-[var(--muted)]">· optional</span>
              <textarea maxLength={1000} rows={3} value={saveDraft.description} onChange={(event) => setSaveDraft({ ...saveDraft, description: event.target.value })} className="mt-1.5 w-full resize-y rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-3 py-2 text-sm outline-none focus:border-[var(--accent)]" />
            </label>
            {saveError && <p role="alert" className="mt-3 text-xs text-[var(--danger)]">{saveError}</p>}
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" onClick={() => setSaveDraft(null)} disabled={saving} className="h-9 rounded-lg border border-[var(--border)] px-3 text-xs transition-colors hover:bg-[var(--surface-hover)] disabled:opacity-50">Cancel</button>
              <button type="submit" disabled={saving || !saveDraft.name.trim()} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 text-xs font-semibold text-[var(--accent-foreground)] transition-colors hover:bg-[var(--accent-strong)] disabled:opacity-60">
                {saving && <LoaderCircle size={13} className="animate-spin" />}{saving ? "Saving…" : saveDraft.id ? "Update query" : "Save query"}
              </button>
            </div>
          </form>
        </div>
      )}

      {deleteTarget && (
        <div className="fixed inset-0 z-[80] grid place-items-center bg-black/65 px-4 py-6" role="presentation">
          <section role="alertdialog" aria-modal="true" aria-labelledby="delete-query-title" onKeyDown={(event) => { if (event.key === "Escape" && !deleting) setDeleteTarget(null); }} className="w-full max-w-sm rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 shadow-2xl">
            <div className="flex items-start gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[color-mix(in_srgb,var(--danger)_12%,transparent)] text-[var(--danger)]"><Trash2 size={16} /></span>
              <div>
                <h2 id="delete-query-title" className="text-sm font-semibold">Delete {deleteTarget.kind === "saved" ? "saved query" : "history entry"}?</h2>
                <p className="mt-1 break-words text-xs text-[var(--muted)]">{deleteTarget.label} will be permanently removed.</p>
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" onClick={() => setDeleteTarget(null)} disabled={deleting} className="h-9 rounded-lg border border-[var(--border)] px-3 text-xs transition-colors hover:bg-[var(--surface-hover)]">Cancel</button>
              <button type="button" onClick={() => void confirmDelete()} disabled={deleting} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[var(--danger)] px-3 text-xs font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60">
                {deleting && <LoaderCircle size={13} className="animate-spin" />}Delete
              </button>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
