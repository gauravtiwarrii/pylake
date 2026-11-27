"use client";

import Link from "next/link";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { AskCitation, AskAnswer } from "./types";

export function AskChart({ answer }: { answer: AskAnswer }) {
  const rows = (answer.rows ?? []).slice(0, 200);
  const suggestion = answer.chart_suggestion;
  if (!suggestion || rows.length === 0) return null;
  if (suggestion.type === "table") return <p data-testid="ask-chart-table" className="rounded-xl border border-[var(--border)] bg-[var(--surface-raised)] p-3 text-xs text-[var(--muted)]">Table view selected for these results.</p>;
  if (suggestion.type === "kpi") {
    const value = rows[0]?.[suggestion.y];
    return (
      <div data-testid="ask-chart-kpi" className="rounded-xl border border-[var(--border)] bg-[var(--surface-raised)] p-5">
        <p className="text-xs text-[var(--muted)]">{suggestion.y || "Result"}</p>
        <p className="mt-2 text-3xl font-semibold tabular-nums">{String(value ?? "—")}</p>
      </div>
    );
  }
  if (suggestion.type === "line") return (
    <div data-testid="ask-chart-line" aria-label="line chart" className="h-64 w-full rounded-xl border border-[var(--border)] bg-[var(--surface-raised)] p-3">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
          <XAxis dataKey={suggestion.x} stroke="var(--muted)" />
          <YAxis stroke="var(--muted)" />
          <Tooltip />
          <Line type="monotone" dataKey={suggestion.y} stroke="var(--accent)" strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
  return (
    <div data-testid="ask-chart-bar" aria-label="bar chart" className="h-64 w-full rounded-xl border border-[var(--border)] bg-[var(--surface-raised)] p-3">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
          <XAxis dataKey={suggestion.x} stroke="var(--muted)" />
          <YAxis stroke="var(--muted)" />
          <Tooltip />
          <Bar dataKey={suggestion.y} fill="var(--accent)" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function CitationChips({ citations, workspaceId }: { citations: AskCitation[]; workspaceId: string }) {
  if (!citations.length) return null;
  const hrefFor = (item: AskCitation) => {
    if (item.type === "pipeline") return `/workspaces/${workspaceId}/pipelines`;
    if (item.type === "dataset") return `/workspaces/${workspaceId}/data?datasetId=${encodeURIComponent(item.id)}`;
    if (item.type === "snapshot") return `/workspaces/${workspaceId}/catalog?assetId=${encodeURIComponent(item.id)}`;
    return `/workspaces/${workspaceId}/catalog?search=${encodeURIComponent(item.name)}`;
  };
  return (
    <ul aria-label="Sources" className="flex flex-wrap gap-2">
      {citations.map((item, index) => (
        <li key={`${item.type}-${item.id}-${item.column ?? index}`}>
          <Link href={hrefFor(item)} className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--surface-raised)] px-2.5 py-1 text-xs text-[var(--muted)] hover:border-[var(--accent)] hover:text-[var(--foreground)]">
            <span className="uppercase tracking-wide">{item.type}</span>
            <span>{item.name}{item.column ? ` · ${item.column}` : ""}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function ClarificationOptions({
  tables,
  columns,
  onChoose,
}: {
  tables: NonNullable<AskAnswer["candidate_tables"]>;
  columns: NonNullable<AskAnswer["candidate_columns"]>;
  onChoose: (refinement: { kind: "table" | "column"; name: string; table?: string }) => void;
}) {
  if (!tables.length && !columns.length) return null;
  return (
    <section aria-label="Clarification options" className="mt-4 space-y-3">
      {tables.length > 0 && <div>
        <h3 className="text-xs font-semibold text-[var(--muted)]">Tables to try</h3>
        <div className="mt-2 flex flex-wrap gap-2">{tables.map((table) => <button key={table.id} type="button" onClick={() => onChoose({ kind: "table", name: table.name })} className="rounded-lg border border-[var(--border)] px-3 py-2 text-xs hover:bg-[var(--surface-hover)]">{table.name}</button>)}</div>
      </div>}
      {columns.length > 0 && <div>
        <h3 className="text-xs font-semibold text-[var(--muted)]">Columns to try</h3>
        <div className="mt-2 flex flex-wrap gap-2">{columns.map((column, index) => <button key={`${column.asset_id ?? column.table}-${column.name}-${index}`} type="button" onClick={() => onChoose({ kind: "column", name: column.name, table: column.table })} className="rounded-lg border border-[var(--border)] px-3 py-2 text-xs hover:bg-[var(--surface-hover)]">{column.name}{column.table ? ` · ${column.table}` : ""}</button>)}</div>
      </div>}
    </section>
  );
}
