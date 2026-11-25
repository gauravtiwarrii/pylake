"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";

const Editor = dynamic(() => import("@monaco-editor/react"), { ssr: false });

type CatalogTable = {
  name: string;
  display_name: string;
  layer: "BRONZE" | "SILVER" | "GOLD";
  version: number;
  columns: { name: string; type: string }[];
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
  execution_status: "SUCCESS" | "FAILED";
  execution_duration_ms: number | null;
  rows_returned: number | null;
  created_at: string;
};

type SavedQuery = {
  id: string;
  name: string;
  description: string | null;
  sql_text: string;
};

export default function SqlWorkspacePage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = use(params);
  const { user } = useAuth();
  const [catalog, setCatalog] = useState<CatalogTable[]>([]);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [saved, setSaved] = useState<SavedQuery[]>([]);
  const [sql, setSql] = useState("-- Select a Silver or Gold lakehouse table\nSELECT 1 AS value");
  const [result, setResult] = useState<SqlResult | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setError("");
    const [catalogResult, historyResult, savedResult] = await Promise.all([
      api<{ items: CatalogTable[] }>(`/api/v1/workspaces/${workspaceId}/sql/catalog`),
      api<HistoryItem[]>(`/api/v1/workspaces/${workspaceId}/sql/history?page=1&page_size=25`),
      api<SavedQuery[]>(`/api/v1/workspaces/${workspaceId}/sql/saved`),
    ]);
    if (catalogResult.error) setError(catalogResult.error);
    else setCatalog(catalogResult.data?.items ?? []);
    if (!historyResult.error) setHistory(historyResult.data ?? []);
    if (!savedResult.error) setSaved(savedResult.data ?? []);
  }, [workspaceId]);

  useEffect(() => {
    if (!user) return;
    const timeout = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timeout);
  }, [load, user]);

  const execute = async () => {
    setRunning(true);
    setError("");
    const response = await api<SqlResult>(
      `/api/v1/workspaces/${workspaceId}/sql/execute`,
      { method: "POST", body: JSON.stringify({ sql }) },
    );
    setRunning(false);
    if (response.error) setError(response.error);
    else if (response.data) setResult(response.data);
    await load();
  };

  const save = async () => {
    const name = window.prompt("Saved query name");
    if (!name) return;
    const response = await api<SavedQuery>(
      `/api/v1/workspaces/${workspaceId}/sql/saved`,
      { method: "POST", body: JSON.stringify({ name, sql_text: sql }) },
    );
    if (response.error) setError(response.error);
    else await load();
  };

  const exportCsv = () => {
    if (!result) return;
    const escape = (value: unknown) => {
      const text = value === null || value === undefined ? "" : String(value);
      return `"${text.replaceAll('"', '""')}"`;
    };
    const lines = [
      result.columns.map((column) => escape(column.name)).join(","),
      ...result.rows.map((row) =>
        result.columns.map((column) => escape(row[column.name])).join(","),
      ),
    ];
    const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "pylake-results.csv";
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <main className="min-h-screen px-4 py-6 md:px-6">
      <div className="mx-auto max-w-[1600px]">
        <Link href={`/workspaces/${workspaceId}`} className="text-sm text-[#98a0b3]">Back to workspace</Link>
        <div className="mt-2 flex items-center justify-between">
          <h1 className="text-2xl font-semibold">SQL Workspace</h1>
          <span className="text-xs text-[#98a0b3]">DuckDB read-only engine</span>
        </div>

        {error && <div className="mt-4 rounded-md border border-red-900 bg-red-950/40 px-4 py-3 text-sm text-red-300">{error}</div>}

        <div className="mt-5 grid min-h-[760px] gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
          <aside className="rounded-lg border border-[#242936] bg-[#11141b] p-3">
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search catalog"
              className="h-9 w-full rounded-md border border-[#303646] bg-[#0b0d12] px-3 text-sm outline-none"
            />
            <p className="mt-4 text-xs font-medium uppercase tracking-wide text-[#98a0b3]">Catalog</p>
            <div className="mt-2 space-y-2">
              {catalog
                .filter((table) => table.name.toLowerCase().includes(search.toLowerCase()))
                .map((table) => (
                  <details key={table.name} className="rounded-md border border-[#242936] p-2">
                    <summary className="cursor-pointer text-sm">{table.name}</summary>
                    <p className="mt-2 text-xs text-[#98a0b3]">{table.layer} · v{table.version}</p>
                    <button
                      onClick={() => setSql(`SELECT *\nFROM ${table.name}\nLIMIT 100`)}
                      className="mt-2 text-xs text-[#7dd3fc]"
                    >
                      Insert preview
                    </button>
                    <div className="mt-2 space-y-1">
                      {table.columns.map((column) => (
                        <p key={column.name} className="font-mono text-xs text-[#c2c7d0]">
                          {column.name}: {column.type}
                        </p>
                      ))}
                    </div>
                  </details>
                ))}
            </div>

            <p className="mt-5 text-xs font-medium uppercase tracking-wide text-[#98a0b3]">Saved queries</p>
            <div className="mt-2 space-y-1">
              {saved.map((item) => (
                <button
                  key={item.id}
                  onClick={() => setSql(item.sql_text)}
                  className="block w-full rounded px-2 py-2 text-left text-sm text-[#c2c7d0] hover:bg-[#191d27]"
                >
                  {item.name}
                </button>
              ))}
            </div>
          </aside>

          <div className="grid min-w-0 gap-4">
            <section className="overflow-hidden rounded-lg border border-[#242936] bg-[#11141b]">
              <div className="flex h-12 items-center justify-between border-b border-[#242936] px-3">
                <span className="text-sm text-[#98a0b3]">Query 1</span>
                <div className="flex gap-2">
                  <button onClick={save} className="h-8 rounded-md border border-[#303646] px-3 text-sm">Save</button>
                  <button
                    onClick={execute}
                    disabled={running}
                    className="h-8 rounded-md bg-[#7dd3fc] px-4 text-sm font-medium text-[#071018] disabled:opacity-60"
                  >
                    {running ? "Running..." : "Run"}
                  </button>
                </div>
              </div>
              <div onKeyDown={(event) => {
                if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                  event.preventDefault();
                  void execute();
                }
                if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
                  event.preventDefault();
                  void save();
                }
              }}>
                <Editor
                  height="280px"
                  defaultLanguage="sql"
                  language="sql"
                  theme="vs-dark"
                  value={sql}
                  onChange={(value) => setSql(value ?? "")}
                  options={{
                    minimap: { enabled: false },
                    fontSize: 14,
                    scrollBeyondLastLine: false,
                    automaticLayout: true,
                    tabSize: 2,
                  }}
                />
              </div>
            </section>

            <section className="min-h-[300px] overflow-hidden rounded-lg border border-[#242936] bg-[#11141b]">
              <div className="flex h-12 items-center justify-between border-b border-[#242936] px-4">
                <span className="text-sm">Results</span>
                {result && (
                  <button onClick={exportCsv} className="h-8 rounded-md border border-[#303646] px-3 text-sm">Export CSV</button>
                )}
              </div>
              {result ? (
                <>
                  <div className="flex gap-5 px-4 py-3 text-xs text-[#98a0b3]">
                    <span>{result.returned_rows} rows</span>
                    <span>{result.duration_ms} ms</span>
                    {result.truncated && <span className="text-amber-300">Results truncated</span>}
                  </div>
                  <div className="max-h-[420px] overflow-auto">
                    <table className="w-full min-w-[640px] text-left text-sm">
                      <thead className="sticky top-0 bg-[#191d27]">
                        <tr>
                          {result.columns.map((column) => (
                            <th key={column.name} className="px-3 py-2">
                              <span>{column.name}</span>
                              <span className="ml-2 text-xs font-normal text-[#98a0b3]">{column.type}</span>
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {result.rows.map((row, index) => (
                          <tr key={index} className="border-t border-[#242936]">
                            {result.columns.map((column) => (
                              <td key={column.name} className="max-w-80 truncate px-3 py-2">
                                {row[column.name] === null || row[column.name] === undefined
                                  ? "null"
                                  : typeof row[column.name] === "object"
                                    ? JSON.stringify(row[column.name])
                                    : String(row[column.name])}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : (
                <p className="px-4 py-6 text-sm text-[#98a0b3]">Run a query to view results.</p>
              )}
            </section>

            <section className="rounded-lg border border-[#242936] bg-[#11141b] p-4">
              <h2 className="font-medium">Query history</h2>
              <div className="mt-3 divide-y divide-[#242936]">
                {history.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => setSql(item.sql_text)}
                    className="w-full py-3 text-left"
                  >
                    <p className="truncate font-mono text-xs text-[#c2c7d0]">{item.sql_text}</p>
                    <p className="mt-1 text-xs text-[#98a0b3]">{item.execution_status} · {item.execution_duration_ms ?? 0} ms · {item.rows_returned ?? 0} rows</p>
                  </button>
                ))}
              </div>
            </section>
          </div>
        </div>
      </div>
    </main>
  );
}
