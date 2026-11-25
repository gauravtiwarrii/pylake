"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  FileJson,
  FileSpreadsheet,
  FileText,
  Filter,
  RefreshCw,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { api, API_URL } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";

type Dataset = {
  id: string;
  name: string;
  original_filename: string;
  description: string | null;
  file_format: string;
  mime_type: string;
  file_size_bytes: number;
  ingestion_status: "PENDING" | "VALIDATING" | "PROCESSING" | "COMPLETED" | "FAILED";
  ingestion_error: string | null;
  schema_json: Record<string, unknown> | null;
  row_count: number | null;
  column_count: number | null;
  created_at: string;
  updated_at: string;
};

type Preview = {
  columns: { name: string; type: string; nullable: boolean }[];
  rows: Record<string, unknown>[];
  row_count: number;
  returned_rows: number;
};

type WorkspaceMember = {
  user_id: string;
  role: "OWNER" | "ADMIN" | "EDITOR" | "VIEWER";
};

function csrfToken(): string {
  const match = document.cookie.split("; ").find((entry) => entry.startsWith("pylake_csrf="));
  return match?.slice("pylake_csrf=".length) ?? "";
}

function sizeLabel(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(value: string) {
  return new Date(value).toLocaleString();
}

function formatIcon(format: string) {
  if (format === "xlsx") return FileSpreadsheet;
  if (format === "json") return FileJson;
  return FileText;
}

export default function DataExplorerPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const { user } = useAuth();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [selected, setSelected] = useState<Dataset | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [schema, setSchema] = useState<{ format: string; columns: { name: string; type: string; nullable: boolean }[] } | null>(null);
  const [search, setSearch] = useState("");
  const [format, setFormat] = useState("");
  const [sort, setSort] = useState("newest");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Dataset | null>(null);
  const [detailTab, setDetailTab] = useState<"overview" | "preview" | "schema">("overview");
  const [canManage, setCanManage] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    const result = await api<{ items: Dataset[]; total: number }>(
      `/api/v1/workspaces/${workspaceId}/datasets?page=${page}&page_size=${pageSize}${search ? `&search=${encodeURIComponent(search)}` : ""}`,
    );
    setLoading(false);
    if (result.error) setError(result.error);
    else {
      let items = result.data?.items ?? [];
      if (format) items = items.filter((dataset) => dataset.file_format === format);
      if (sort === "name") items = [...items].sort((a, b) => a.name.localeCompare(b.name));
      if (sort === "size") items = [...items].sort((a, b) => b.file_size_bytes - a.file_size_bytes);
      if (sort === "oldest") items = [...items].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
      setDatasets(items);
      setTotal(format ? items.length : result.data?.total ?? 0);
    }
  }, [format, page, pageSize, search, sort, workspaceId]);

  useEffect(() => {
    if (!user) return;
    const timeout = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timeout);
  }, [load, user]);

  useEffect(() => {
    if (!user) return;
    api<WorkspaceMember[]>(`/api/v1/workspaces/${workspaceId}/members`).then((result) => {
      const current = result.data?.find((member) => member.user_id === user.id);
      setCanManage(current?.role === "OWNER" || current?.role === "ADMIN" || current?.role === "EDITOR");
    });
  }, [user, workspaceId]);

  const selectDataset = async (dataset: Dataset) => {
    setSelected(dataset);
    setDetailTab("overview");
    setPreview(null);
    setSchema(null);
    setError("");
    const [schemaResult, previewResult] = await Promise.all([
      api<{ format: string; columns: { name: string; type: string; nullable: boolean }[] }>(
        `/api/v1/workspaces/${workspaceId}/datasets/${dataset.id}/schema`,
      ),
      dataset.ingestion_status === "COMPLETED"
        ? api<Preview>(`/api/v1/workspaces/${workspaceId}/datasets/${dataset.id}/preview?limit=100`)
        : Promise.resolve({} as { data?: Preview; error?: string }),
    ]);
    if (schemaResult.data) setSchema(schemaResult.data);
    if (previewResult.data) setPreview(previewResult.data);
    if (previewResult.error) setError(previewResult.error);
  };

  const validateFile = (file: File) => {
    const allowed = [".csv", ".json", ".ndjson", ".parquet", ".xlsx"];
    const lower = file.name.toLowerCase();
    if (!allowed.some((extension) => lower.endsWith(extension))) return "Choose a CSV, JSON, NDJSON, Parquet, or XLSX file.";
    if (file.size === 0) return "The selected file is empty.";
    if (file.size > 100 * 1024 * 1024) return "The selected file exceeds the 100 MB upload limit.";
    return "";
  };

  const chooseFile = (file: File) => {
    const validationError = validateFile(file);
    setUploadFile(file);
    setUploadError(validationError);
  };

  const upload = () => {
    if (!uploadFile) return;
    const validationError = validateFile(uploadFile);
    if (validationError) {
      setUploadError(validationError);
      return;
    }
    setUploadError("");
    setError("");
    setProgress(0);
    const form = new FormData();
    form.append("file", uploadFile);
    form.append("name", uploadFile.name.replace(/\.[^.]+$/, ""));
    const request = new XMLHttpRequest();
    request.open("POST", `${API_URL}/api/v1/workspaces/${workspaceId}/datasets/upload`);
    request.withCredentials = true;
    request.setRequestHeader("X-CSRF-Token", csrfToken());
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) setProgress(Math.round((event.loaded / event.total) * 100));
    };
    request.onload = () => {
      setProgress(null);
      if (request.status >= 200 && request.status < 300) {
        setUploadOpen(false);
        setUploadFile(null);
        setNotice("Dataset uploaded and ingested successfully.");
        void load();
      } else {
        try {
          setUploadError(JSON.parse(request.responseText)?.detail ?? "Upload failed.");
        } catch {
          setUploadError("Upload failed.");
        }
      }
    };
    request.onerror = () => {
      setProgress(null);
      setUploadError("Upload could not reach the server.");
    };
    request.send(form);
  };

  const deleteDataset = async () => {
    if (!deleteTarget) return;
    setError("");
    const result = await api(
      `/api/v1/workspaces/${workspaceId}/datasets/${deleteTarget.id}`,
      { method: "DELETE" },
    );
    if (result.error) setError(result.error);
    else {
      setNotice("Dataset deleted.");
      setSelected(null);
      setPreview(null);
      setSchema(null);
      setDeleteTarget(null);
      await load();
    }
  };

  const maxPage = Math.max(1, Math.ceil(total / pageSize));

  return (
    <main className="min-h-[calc(100vh-64px)] px-4 py-6 md:px-7 lg:px-8">
      <div className="mx-auto max-w-[1600px]">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.16em] text-[var(--accent)]">Workspace data</p>
            <h2 className="mt-1 text-2xl font-semibold tracking-tight">Data Explorer</h2>
            <p className="mt-1 text-sm text-[var(--muted)]">Browse, inspect, and manage uploaded datasets.</p>
          </div>
          {canManage && (
            <button onClick={() => setUploadOpen(true)} className="flex h-10 items-center justify-center gap-2 rounded-lg bg-[var(--accent)] px-4 text-sm font-medium text-[var(--accent-foreground)]">
              <Upload size={16} /> Upload dataset
            </button>
          )}
        </div>

        {notice && (
          <div className="mt-5 flex items-center justify-between rounded-lg border border-[color-mix(in_srgb,var(--success)_35%,transparent)] bg-[color-mix(in_srgb,var(--success)_8%,var(--surface))] px-4 py-3 text-sm">
            <span>{notice}</span>
            <button onClick={() => setNotice("")} aria-label="Dismiss"><X size={14} /></button>
          </div>
        )}
        {error && (
          <div className="mt-5 flex items-center justify-between rounded-lg border border-[color-mix(in_srgb,var(--danger)_35%,transparent)] bg-[color-mix(in_srgb,var(--danger)_8%,var(--surface))] px-4 py-3 text-sm">
            <span>{error}</span>
            <button onClick={() => setError("")} aria-label="Dismiss"><X size={14} /></button>
          </div>
        )}

        <div className="mt-6 grid gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 md:grid-cols-[minmax(220px,1fr)_160px_160px_auto]">
          <label className="relative">
            <Search size={15} className="absolute left-3 top-3 text-[var(--muted)]" />
            <input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="Search datasets" className="h-10 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] pl-9 pr-3 text-sm outline-none focus:border-[var(--accent)]" />
          </label>
          <select value={format} onChange={(event) => { setFormat(event.target.value); setPage(1); }} className="h-10 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-3 text-sm">
            <option value="">All formats</option>
            <option value="csv">CSV</option>
            <option value="json">JSON</option>
            <option value="ndjson">NDJSON</option>
            <option value="parquet">Parquet</option>
            <option value="xlsx">XLSX</option>
          </select>
          <select value={sort} onChange={(event) => setSort(event.target.value)} className="h-10 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-3 text-sm">
            <option value="newest">Newest</option>
            <option value="oldest">Oldest</option>
            <option value="name">Name</option>
            <option value="size">Largest</option>
          </select>
          <button onClick={() => void load()} className="grid h-10 place-items-center rounded-lg border border-[var(--border)] px-3 text-[var(--muted)] hover:text-[var(--foreground)]" aria-label="Refresh">
            <RefreshCw size={15} />
          </button>
        </div>

        <div className="mt-5 grid min-h-[620px] gap-5 xl:grid-cols-[minmax(520px,1fr)_420px]">
          <section className="min-w-0 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
            <div className="flex h-12 items-center justify-between border-b border-[var(--border)] px-4">
              <span className="text-sm font-medium">{loading ? "Loading..." : `${total} datasets`}</span>
              <div className="flex items-center gap-2 text-xs text-[var(--muted)]"><Filter size={13} /> {format ? format.toUpperCase() : "All formats"}</div>
            </div>
            {loading ? (
              <div className="divide-y divide-[var(--border)]">{[0, 1, 2, 3, 4].map((item) => <div key={item} className="h-16 animate-pulse bg-[color-mix(in_srgb,var(--surface-hover)_45%,transparent)]" />)}</div>
            ) : datasets.length === 0 ? (
              <div className="grid min-h-[500px] place-items-center p-8 text-center">
                <div>
                  <div className="mx-auto grid size-12 place-items-center rounded-xl border border-[var(--border)] bg-[var(--surface-raised)]"><DatabaseIcon /></div>
                  <p className="mt-4 font-medium">No datasets found</p>
                  <p className="mt-1 text-sm text-[var(--muted)]">{search || format ? "Try changing your filters." : "Upload a dataset to get started."}</p>
                </div>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[620px] text-left">
                  <thead className="text-xs text-[var(--muted)]">
                    <tr className="h-11 border-b border-[var(--border)]">
                      <th className="px-4 font-medium">Name</th>
                      <th className="px-4 font-medium">Format</th>
                      <th className="px-4 font-medium">Rows</th>
                      <th className="px-4 font-medium">Size</th>
                      <th className="px-4 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border)]">
                    {datasets.map((dataset) => {
                      const Icon = formatIcon(dataset.file_format);
                      return (
                        <tr key={dataset.id} onClick={() => void selectDataset(dataset)} className={`cursor-pointer text-sm transition-colors ${selected?.id === dataset.id ? "bg-[var(--surface-hover)]" : "hover:bg-[var(--surface-raised)]"}`}>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-3">
                              <div className="grid size-9 shrink-0 place-items-center rounded-lg border border-[var(--border)] bg-[var(--surface-raised)]"><Icon size={16} /></div>
                              <div className="min-w-0"><p className="truncate font-medium">{dataset.name}</p><p className="truncate text-xs text-[var(--muted)]">{formatDate(dataset.created_at)}</p></div>
                            </div>
                          </td>
                          <td className="px-4 py-3"><span className="rounded-md border border-[var(--border)] px-2 py-1 text-xs uppercase">{dataset.file_format}</span></td>
                          <td className="px-4 py-3 text-[var(--muted)]">{dataset.row_count?.toLocaleString() ?? "—"}</td>
                          <td className="px-4 py-3 text-[var(--muted)]">{sizeLabel(dataset.file_size_bytes)}</td>
                          <td className="px-4 py-3"><IngestionStatus status={dataset.ingestion_status} /></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {!loading && datasets.length > 0 && (
              <div className="flex h-12 items-center justify-between border-t border-[var(--border)] px-4">
                <span className="text-xs text-[var(--muted)]">Page {page} of {maxPage}</span>
                <div className="flex gap-1">
                  <button disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))} className="grid size-8 place-items-center rounded-md border border-[var(--border)] disabled:opacity-40"><ChevronLeft size={14} /></button>
                  <button disabled={page >= maxPage} onClick={() => setPage((value) => value + 1)} className="grid size-8 place-items-center rounded-md border border-[var(--border)] disabled:opacity-40"><ChevronRight size={14} /></button>
                </div>
              </div>
            )}
          </section>

          <aside className="min-w-0 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
            {!selected ? (
              <div className="grid min-h-[620px] place-items-center p-8 text-center">
                <div><p className="font-medium">Dataset details</p><p className="mt-1 text-sm text-[var(--muted)]">Select a dataset to inspect metadata and preview data.</p></div>
              </div>
            ) : (
              <>
                <div className="border-b border-[var(--border)] p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0"><p className="truncate font-semibold">{selected.name}</p><p className="mt-1 truncate text-xs text-[var(--muted)]">{selected.original_filename}</p></div>
                    {canManage && (
                      <button onClick={() => setDeleteTarget(selected)} className="grid size-8 shrink-0 place-items-center rounded-md border border-[color-mix(in_srgb,var(--danger)_35%,transparent)] text-[var(--danger)]" aria-label="Delete dataset"><Trash2 size={15} /></button>
                    )}
                  </div>
                  <div className="mt-4 flex gap-1 border-b border-[var(--border)]">
                    {(["overview", "preview", "schema"] as const).map((tab) => (
                      <button key={tab} onClick={() => setDetailTab(tab)} className={`border-b px-3 py-2 text-xs capitalize ${detailTab === tab ? "border-[var(--accent)] text-[var(--foreground)]" : "border-transparent text-[var(--muted)]"}`}>{tab}</button>
                    ))}
                  </div>
                </div>

                <div className="max-h-[620px] overflow-y-auto p-5">
                  {detailTab === "overview" && (
                    <div className="space-y-4">
                      <DetailRow label="Format" value={selected.file_format.toUpperCase()} />
                      <DetailRow label="Rows" value={selected.row_count?.toLocaleString() ?? "Unknown"} />
                      <DetailRow label="Columns" value={selected.column_count?.toLocaleString() ?? "Unknown"} />
                      <DetailRow label="File size" value={sizeLabel(selected.file_size_bytes)} />
                      <DetailRow label="Created" value={formatDate(selected.created_at)} />
                      <DetailRow label="Updated" value={formatDate(selected.updated_at)} />
                      <DetailRow label="Status" value={selected.ingestion_status} />
                      {selected.ingestion_error && <p className="rounded-lg border border-[color-mix(in_srgb,var(--danger)_35%,transparent)] p-3 text-xs text-[var(--danger)]">{selected.ingestion_error}</p>}
                      <a href={`${API_URL}/api/v1/workspaces/${workspaceId}/datasets/${selected.id}/download`} className="flex h-10 items-center justify-center gap-2 rounded-lg border border-[var(--border)] text-sm hover:border-[var(--border-strong)]">
                        <Download size={15} /> Download original
                      </a>
                    </div>
                  )}

                  {detailTab === "preview" && (
                    selected.ingestion_status === "COMPLETED" ? preview ? (
                      <div className="overflow-auto rounded-lg border border-[var(--border)]">
                        <table className="min-w-[600px] text-left text-xs">
                          <thead className="border-b border-[var(--border)]"><tr>{preview.columns.map((column) => <th key={column.name} className="px-3 py-2"><span>{column.name}</span><span className="ml-1 text-[var(--muted)]">{column.type}</span></th>)}</tr></thead>
                          <tbody>{preview.rows.map((row, index) => (
                            <tr key={index} className="border-b border-[var(--border)] last:border-0">{preview.columns.map((column) => <td key={column.name} className="max-w-48 truncate px-3 py-2">{row[column.name] === null || row[column.name] === undefined ? <span className="text-[var(--muted)]">null</span> : typeof row[column.name] === "object" ? JSON.stringify(row[column.name]) : String(row[column.name])}</td>)}</tr>
                          ))}</tbody>
                        </table>
                      </div>
                    ) : <p className="text-sm text-[var(--muted)]">Loading preview...</p> : (
                      <p className="text-sm text-[var(--muted)]">Preview is unavailable until ingestion completes.</p>
                    )
                  )}

                  {detailTab === "schema" && (
                    schema?.columns?.length ? (
                      <div className="space-y-2">
                        {schema.columns.map((column, index) => (
                          <div key={column.name} className="rounded-lg border border-[var(--border)] p-3">
                            <div className="flex items-center justify-between"><p className="font-mono text-xs">{column.name}</p><span className="text-xs text-[var(--muted)]">#{index + 1}</span></div>
                            <p className="mt-2 text-xs text-[var(--muted)]">{column.type}{column.nullable ? " · nullable" : " · non-nullable"}</p>
                          </div>
                        ))}
                      </div>
                    ) : <p className="text-sm text-[var(--muted)]">Schema metadata is unavailable.</p>
                  )}
                </div>
              </>
            )}
          </aside>
        </div>
      </div>

      {uploadOpen && (
        <div className="fixed inset-0 z-[60] grid place-items-center bg-black/70 px-4">
          <div className="w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-2xl">
            <div className="flex items-start justify-between">
              <div><h3 className="font-semibold">Upload dataset</h3><p className="mt-1 text-xs text-[var(--muted)]">CSV, JSON, NDJSON, Parquet or XLSX · Maximum 100 MB</p></div>
              <button onClick={() => { setUploadOpen(false); setUploadFile(null); setUploadError(""); }} className="grid size-8 place-items-center rounded-md text-[var(--muted)] hover:bg-[var(--surface-hover)]"><X size={16} /></button>
            </div>
            <div
              onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => { event.preventDefault(); setDragging(false); const file = event.dataTransfer.files[0]; if (file) chooseFile(file); }}
              className={`mt-5 grid min-h-52 place-items-center rounded-xl border border-dashed p-6 text-center ${dragging ? "border-[var(--accent)] bg-[color-mix(in_srgb,var(--accent)_6%,var(--surface))]" : "border-[var(--border-strong)]"}`}
            >
              {uploadFile ? (
                <div className="w-full">
                  <div className="mx-auto grid size-11 place-items-center rounded-xl border border-[var(--border)]"><Upload size={18} /></div>
                  <p className="mt-3 truncate font-medium">{uploadFile.name}</p>
                  <p className="mt-1 text-xs text-[var(--muted)]">{sizeLabel(uploadFile.size)} · {uploadFile.name.split(".").pop()?.toUpperCase()}</p>
                </div>
              ) : (
                <div>
                  <div className="mx-auto grid size-11 place-items-center rounded-xl border border-[var(--border)]"><Upload size={18} /></div>
                  <p className="mt-3 text-sm">Drop a file here</p>
                  <p className="mt-1 text-xs text-[var(--muted)]">or choose it from your device</p>
                </div>
              )}
            </div>
            <input ref={fileInput} type="file" accept=".csv,.json,.ndjson,.parquet,.xlsx" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) chooseFile(file); event.currentTarget.value = ""; }} />
            <div className="mt-4 flex items-center gap-2">
              <button onClick={() => fileInput.current?.click()} className="h-10 flex-1 rounded-lg border border-[var(--border)] text-sm">Browse files</button>
              {uploadFile && <button onClick={() => { setUploadFile(null); setUploadError(""); }} className="h-10 rounded-lg border border-[var(--border)] px-3 text-sm">Clear</button>}
            </div>
            {uploadError && <p className="mt-3 text-sm text-[var(--danger)]">{uploadError}</p>}
            {progress !== null && (
              <div className="mt-4"><div className="mb-2 flex justify-between text-xs text-[var(--muted)]"><span>Uploading</span><span>{progress}%</span></div><div className="h-1.5 overflow-hidden rounded-full bg-[var(--surface-hover)]"><div className="h-full rounded-full bg-[var(--accent)]" style={{ width: `${progress}%` }} /></div></div>
            )}
            <div className="mt-5 flex justify-end gap-2">
              <button onClick={() => { setUploadOpen(false); setUploadFile(null); setUploadError(""); }} className="h-10 rounded-lg px-4 text-sm text-[var(--muted)]">Cancel</button>
              <button disabled={!uploadFile || Boolean(uploadError) || progress !== null} onClick={upload} className="h-10 rounded-lg bg-[var(--accent)] px-4 text-sm font-medium text-[var(--accent-foreground)] disabled:opacity-40">Upload dataset</button>
            </div>
          </div>
        </div>
      )}

      {deleteTarget && (
        <div className="fixed inset-0 z-[60] grid place-items-center bg-black/70 px-4">
          <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-2xl">
            <h3 className="font-semibold">Delete dataset</h3>
            <p className="mt-2 text-sm text-[var(--muted)]">Delete <span className="font-medium text-[var(--foreground)]">{deleteTarget.name}</span>? This removes the original dataset and associated storage object.</p>
            <div className="mt-6 flex justify-end gap-2">
              <button onClick={() => setDeleteTarget(null)} className="h-10 rounded-lg px-4 text-sm text-[var(--muted)]">Cancel</button>
              <button onClick={deleteDataset} className="h-10 rounded-lg bg-[color-mix(in_srgb,var(--danger)_18%,var(--surface))] px-4 text-sm font-medium text-[var(--danger)]">Delete dataset</button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

function DatabaseIcon() {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><ellipse cx="12" cy="5" rx="7" ry="3"/><path d="M5 5v7c0 1.7 3.1 3 7 3s7-1.3 7-3V5"/><path d="M5 12v7c0 1.7 3.1 3 7 3s7-1.3 7-3v-7"/></svg>;
}

function IngestionStatus({ status }: { status: Dataset["ingestion_status"] }) {
  const styles = status === "COMPLETED"
    ? "border-[color-mix(in_srgb,var(--success)_35%,transparent)] text-[var(--success)]"
    : status === "FAILED"
      ? "border-[color-mix(in_srgb,var(--danger)_35%,transparent)] text-[var(--danger)]"
      : "border-[var(--border)] text-[var(--muted)]";
  return <span className={`inline-flex rounded-full border px-2 py-1 text-[10px] uppercase ${styles}`}>{status}</span>;
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return <div className="flex items-start justify-between gap-4 border-b border-[var(--border)] pb-3 last:border-0"><span className="text-xs text-[var(--muted)]">{label}</span><span className="max-w-[220px] text-right text-xs font-medium">{value}</span></div>;
}
