"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { Download, Search, Trash2, Upload } from "lucide-react";
import { api, API_URL } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";

type Dataset = {
  id: string;
  name: string;
  original_filename: string;
  description: string | null;
  file_format: string;
  file_size_bytes: number;
  ingestion_status: "PENDING" | "VALIDATING" | "PROCESSING" | "COMPLETED" | "FAILED";
  ingestion_error: string | null;
  schema_json: Record<string, unknown> | null;
  row_count: number | null;
  column_count: number | null;
  created_at: string;
};

type Preview = {
  columns: { name: string; type: string; nullable: boolean }[];
  rows: Record<string, unknown>[];
  row_count: number;
  returned_rows: number;
};

function csrfToken(): string {
  const match = document.cookie
    .split("; ")
    .find((entry) => entry.startsWith("pylake_csrf="));
  return match?.slice("pylake_csrf=".length) ?? "";
}

function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function DataExplorerPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = use(params);
  const { user } = useAuth();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [selected, setSelected] = useState<Dataset | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [progress, setProgress] = useState<number | null>(null);

  const load = useCallback(async (query = search) => {
    const result = await api<{ items: Dataset[] }>(
      `/api/v1/workspaces/${workspaceId}/datasets?page=1&page_size=100${query ? `&search=${encodeURIComponent(query)}` : ""}`,
    );
    if (result.error) setError(result.error);
    else setDatasets(result.data?.items ?? []);
  }, [search, workspaceId]);

  useEffect(() => {
    if (!user) return;
    const timeout = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [load, user]);

  const selectDataset = async (dataset: Dataset) => {
    setSelected(dataset);
    setPreview(null);
    setError("");
    if (dataset.ingestion_status === "COMPLETED") {
      const result = await api<Preview>(
        `/api/v1/workspaces/${workspaceId}/datasets/${dataset.id}/preview?limit=100`,
      );
      if (result.error) setError(result.error);
      else setPreview(result.data ?? null);
    }
  };

  const upload = (file: File) => {
    setError("");
    setProgress(0);
    const form = new FormData();
    form.append("file", file);
    form.append("name", file.name.replace(/\.[^.]+$/, ""));
    const request = new XMLHttpRequest();
    request.open("POST", `${API_URL}/api/v1/workspaces/${workspaceId}/datasets/upload`);
    request.withCredentials = true;
    request.setRequestHeader("X-CSRF-Token", csrfToken());
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) setProgress(Math.round((event.loaded / event.total) * 100));
    };
    request.onload = () => {
      setProgress(null);
      if (request.status >= 200 && request.status < 300) load();
      else {
        try {
          setError(JSON.parse(request.responseText)?.detail ?? "Upload failed");
        } catch {
          setError("Upload failed");
        }
      }
    };
    request.onerror = () => {
      setProgress(null);
      setError("Upload could not reach the server");
    };
    request.send(form);
  };

  const deleteDataset = async (dataset: Dataset) => {
    if (!window.confirm(`Delete "${dataset.name}"?`)) return;
    setError("");
    const result = await api(
      `/api/v1/workspaces/${workspaceId}/datasets/${dataset.id}`,
      { method: "DELETE" },
    );
    if (result.error) setError(result.error);
    else {
      setSelected(null);
      setPreview(null);
      await load();
    }
  };

  return (
    <main className="min-h-screen px-6 py-8 md:px-10">
      <div className="mx-auto max-w-7xl">
        <div className="flex items-center justify-between">
          <div>
            <Link href={`/workspaces/${workspaceId}`} className="text-sm text-[#98a0b3]">
              Back to workspace
            </Link>
            <h1 className="mt-2 text-3xl font-semibold">Data Explorer</h1>
          </div>
          <label className="flex h-10 cursor-pointer items-center gap-2 rounded-md bg-[#7dd3fc] px-4 text-sm font-medium text-[#071018]">
            <Upload size={16} />
            Upload dataset
            <input
              type="file"
              accept=".csv,.json,.parquet,.xlsx"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) upload(file);
                event.currentTarget.value = "";
              }}
            />
          </label>
        </div>

        {progress !== null && (
          <div className="mt-5">
            <div className="mb-2 flex justify-between text-xs text-[#98a0b3]">
              <span>Uploading</span><span>{progress}%</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-[#242936]">
              <div className="h-full bg-[#7dd3fc]" style={{ width: `${progress}%` }} />
            </div>
          </div>
        )}

        {error && <div className="mt-5 rounded-md border border-red-900 bg-red-950/40 px-4 py-3 text-sm text-red-300">{error}</div>}

        <section
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            const file = event.dataTransfer.files[0];
            if (file) upload(file);
          }}
          className="mt-6 rounded-lg border border-dashed border-[#303646] px-5 py-4 text-sm text-[#98a0b3]"
        >
          Drop CSV, JSON, Parquet, or XLSX files here. Maximum 100 MB.
        </section>

        <div className="mt-6 flex gap-3">
          <div className="relative flex-1">
            <Search size={16} className="absolute left-3 top-3 text-[#98a0b3]" />
            <input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                load(event.target.value);
              }}
              placeholder="Search datasets"
              className="h-10 w-full rounded-md border border-[#303646] bg-[#11141b] pl-9 pr-3 text-sm outline-none focus:border-[#7dd3fc]"
            />
          </div>
        </div>

        <div className="mt-6 grid gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
          <div className="space-y-3">
            {datasets.length === 0 ? (
              <div className="rounded-lg border border-[#242936] p-6 text-center text-sm text-[#98a0b3]">
                No datasets uploaded.
              </div>
            ) : datasets.map((dataset) => (
              <button
                key={dataset.id}
                onClick={() => selectDataset(dataset)}
                className={`w-full rounded-lg border p-4 text-left ${
                  selected?.id === dataset.id ? "border-[#7dd3fc] bg-[#11141b]" : "border-[#242936] bg-[#0d1016]"
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-medium">{dataset.name}</p>
                    <p className="mt-1 text-xs text-[#98a0b3]">
                      {dataset.file_format.toUpperCase()} · {sizeLabel(dataset.file_size_bytes)}
                    </p>
                  </div>
                  <Status status={dataset.ingestion_status} />
                </div>
                {dataset.ingestion_error && <p className="mt-3 text-xs text-red-300">{dataset.ingestion_error}</p>}
              </button>
            ))}
          </div>

          <div className="min-w-0 rounded-lg border border-[#242936] bg-[#11141b] p-5">
            {!selected ? (
              <p className="text-sm text-[#98a0b3]">Select a dataset to inspect it.</p>
            ) : (
              <>
                <div className="flex items-start justify-between">
                  <div>
                    <h2 className="font-medium">{selected.name}</h2>
                    <p className="mt-1 text-sm text-[#98a0b3]">{selected.original_filename}</p>
                  </div>
                  <div className="flex gap-2">
                    <a
                      href={`${API_URL}/api/v1/workspaces/${workspaceId}/datasets/${selected.id}/download`}
                      className="grid size-9 place-items-center rounded-md border border-[#303646]"
                      title="Download"
                    >
                      <Download size={16} />
                    </a>
                    <button
                      onClick={() => deleteDataset(selected)}
                      className="grid size-9 place-items-center rounded-md border border-[#513036] text-red-300"
                      title="Delete"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </div>

                {selected.row_count !== null && (
                  <div className="mt-5 grid grid-cols-2 gap-3 text-sm">
                    <div className="rounded-md border border-[#242936] p-3"><span className="text-[#98a0b3]">Rows</span><p className="mt-1 font-medium">{selected.row_count}</p></div>
                    <div className="rounded-md border border-[#242936] p-3"><span className="text-[#98a0b3]">Columns</span><p className="mt-1 font-medium">{selected.column_count}</p></div>
                  </div>
                )}

                {preview ? (
                  <div className="mt-6 overflow-auto">
                    <table className="w-full min-w-[640px] text-left text-sm">
                      <thead>
                        <tr className="border-b border-[#303646]">
                          {preview.columns.map((column) => <th key={column.name} className="px-3 py-2 font-medium">{column.name}</th>)}
                        </tr>
                      </thead>
                      <tbody>
                        {preview.rows.map((row, rowIndex) => (
                          <tr key={rowIndex} className="border-b border-[#242936]">
                            {preview.columns.map((column) => (
                              <td key={column.name} className="max-w-64 truncate px-3 py-2 text-[#c2c7d0]">
                                {row[column.name] === null || row[column.name] === undefined ? "null" : String(row[column.name])}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : selected.ingestion_status !== "COMPLETED" ? (
                  <p className="mt-6 text-sm text-[#98a0b3]">Preview unavailable while ingestion is {selected.ingestion_status.toLowerCase()}.</p>
                ) : null}
              </>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}

function Status({ status }: { status: Dataset["ingestion_status"] }) {
  const styles = status === "COMPLETED"
    ? "border-[#27533c] bg-[#102118] text-[#86efac]"
    : status === "FAILED"
      ? "border-[#513036] bg-[#241316] text-red-300"
      : "border-[#303646] bg-[#191d27] text-[#98a0b3]";
  return <span className={`rounded-full border px-2 py-1 text-xs ${styles}`}>{status}</span>;
}
