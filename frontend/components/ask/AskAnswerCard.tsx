"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Check, Copy } from "lucide-react";
import type { AskAnswer } from "./types";
import { AskChart, CitationChips, ClarificationOptions } from "./AskVisuals";

function display(value: unknown) {
  if (value === null || value === undefined) return "NULL";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

export function AskAnswerCard({
  answer,
  workspaceId,
  onRefine,
}: {
  answer: AskAnswer;
  workspaceId: string;
  onRefine: (refinement: { kind: "table" | "column"; name: string; table?: string }) => void;
}) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState("");
  const rows = (answer.rows ?? answer.table_rows ?? []).slice(0, 200);
  const columns = answer.columns?.map((item) => item.name) ?? Object.keys(rows[0] ?? {});
  const sqlWorkspaceHref = answer.sql
    ? `/workspaces/${workspaceId}/sql?sql=${encodeURIComponent(answer.sql)}`
    : `/workspaces/${workspaceId}/sql`;
  const copySql = async () => {
    if (!answer.sql) return;
    try {
      await navigator.clipboard.writeText(answer.sql);
      setCopied(true);
      setCopyError("");
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopyError("Could not copy SQL. Select and copy it from the query panel.");
    }
  };

  return (
    <article aria-label="Ask answer" className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5 shadow-[var(--shadow-soft)]">
      <header className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-[var(--border)] bg-[var(--surface-raised)] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide">{answer.answer_type}</span>
        <span className="rounded-full border border-[var(--border)] px-2.5 py-1 text-[10px] text-[var(--muted)]">{answer.confidence} confidence</span>
        {answer.ai_used && <span className="rounded-full border border-[color-mix(in_srgb,var(--accent)_35%,var(--border))] bg-[var(--accent-soft)] px-2.5 py-1 text-[10px] text-[var(--accent)]">AI used</span>}
      </header>
      <p className="mt-4 whitespace-pre-wrap text-sm leading-6">{answer.summary}</p>
      {answer.ai_explanation && <p className="mt-4 rounded-lg border border-[color-mix(in_srgb,var(--accent)_35%,var(--border))] bg-[var(--accent-soft)] p-3 text-xs leading-5"><strong>AI estimate:</strong> {answer.ai_explanation}</p>}

      {answer.chart_suggestion && <div className="mt-4"><AskChart answer={answer} /></div>}
      {rows.length > 0 && <div className="mt-4 overflow-x-auto rounded-xl border border-[var(--border)]">
        <table className="w-full min-w-max text-left text-xs">
          <caption className="sr-only">Query or metadata results</caption>
          <thead className="bg-[var(--surface-raised)] text-[var(--muted)]"><tr>{columns.map((column) => <th key={column} scope="col" className="px-3 py-2 font-medium">{column}</th>)}</tr></thead>
          <tbody>{rows.map((row, index) => <tr key={index} className="border-t border-[var(--border)]">{columns.map((column) => <td key={column} className="max-w-80 truncate px-3 py-2" title={display(row[column])}>{display(row[column])}</td>)}</tr>)}</tbody>
        </table>
        {answer.truncated && <p className="border-t border-[var(--border)] px-3 py-2 text-[10px] text-[var(--muted)]">Showing up to 200 rows. Results were truncated.</p>}
      </div>}

      {answer.sql && <details className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--surface-raised)]">
        <summary className="cursor-pointer px-3 py-2.5 text-xs font-medium">Validated SQL</summary>
        <div className="border-t border-[var(--border)] p-3">
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-5">{answer.sql}</pre>
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" onClick={() => void copySql()} className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-2 text-xs hover:bg-[var(--surface-hover)]">{copied ? <Check size={13} /> : <Copy size={13} />}{copied ? "Copied" : "Copy SQL"}</button>
            <Link href={sqlWorkspaceHref} className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 py-2 text-xs font-semibold text-[var(--accent-foreground)] hover:bg-[var(--accent-strong)]">Open in SQL Workspace <ArrowUpRight size={13} /></Link>
          </div>
          {copyError && <p role="alert" className="mt-2 text-xs text-[var(--danger)]">{copyError}</p>}
        </div>
      </details>}

      <ClarificationOptions tables={answer.candidate_tables ?? []} columns={answer.candidate_columns ?? []} onChoose={onRefine} />
      {answer.citations.length > 0 && <section className="mt-4" aria-label="Answer citations"><h3 className="mb-2 text-xs font-semibold text-[var(--muted)]">Sources</h3><CitationChips citations={answer.citations} workspaceId={workspaceId} /></section>}
      {answer.limitations.length > 0 && <section className="mt-4"><h3 className="text-xs font-semibold text-[var(--muted)]">Limitations</h3><ul className="mt-1 list-disc space-y-1 pl-5 text-xs leading-5 text-[var(--muted)]">{answer.limitations.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></section>}
    </article>
  );
}
