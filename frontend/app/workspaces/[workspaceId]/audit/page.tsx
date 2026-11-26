"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { useAIPageContext } from "@/components/ai-page-context";

type AuditItem = {
  id: string;
  actor_id: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

export default function AuditPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = use(params);
  const { user } = useAuth();
  const [items, setItems] = useState<AuditItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  useAIPageContext({ page_type: "audit", active_view: "events" });

  const load = useCallback(async () => {
    const response = await api<{ items: AuditItem[]; total: number }>(
      `/api/v1/workspaces/${workspaceId}/audit?page=${page}&page_size=25`,
    );
    if (response.error) setError(response.error);
    else {
      setItems(response.data?.items ?? []);
      setTotal(response.data?.total ?? 0);
    }
  }, [page, workspaceId]);

  useEffect(() => {
    if (!user) return;
    const timeout = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timeout);
  }, [load, user]);

  return (
    <main className="min-h-[calc(100vh-64px)] px-4 py-6 md:px-7 lg:px-8">
      <div className="mx-auto max-w-[1400px]">
        <Link href={`/workspaces/${workspaceId}`} className="text-xs text-[var(--muted)] hover:text-[var(--accent)]">Workspace / Overview</Link>
        <p className="mt-3 text-xs font-medium uppercase tracking-[0.16em] text-[var(--accent)]">Governance</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">Audit log</h1>
        {error && <div className="mt-5 rounded-lg border border-[color-mix(in_srgb,var(--danger)_35%,transparent)] bg-[color-mix(in_srgb,var(--danger)_8%,var(--surface))] px-4 py-3 text-sm text-[var(--danger)]">{error}</div>}
        <div className="mt-6 overflow-x-auto rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-soft)]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[var(--surface-raised)] text-xs text-[var(--muted)]">
              <tr><th className="px-4 py-3">Action</th><th className="px-4 py-3">Target</th><th className="px-4 py-3">Time</th></tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} className="border-t border-[var(--border)] transition-colors hover:bg-[var(--surface-raised)]">
                  <td className="px-4 py-3">{item.action}</td>
                  <td className="px-4 py-3 font-mono text-xs text-[var(--muted)]">{item.target_type}:{item.target_id ?? "-"}</td>
                  <td className="px-4 py-3 text-[var(--muted)]">{new Date(item.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {items.length === 0 && !error && <p className="mt-5 text-sm text-[var(--muted)]">No audit events.</p>}
        <div className="mt-4 flex items-center justify-between text-sm text-[var(--muted)]">
          <span>{total} events</span>
          <div className="flex gap-2">
            <button disabled={page === 1} onClick={() => setPage((value) => value - 1)} className="rounded-lg border border-[var(--border-strong)] px-3 py-2 disabled:opacity-40">Previous</button>
            <button disabled={page * 25 >= total} onClick={() => setPage((value) => value + 1)} className="rounded-lg border border-[var(--border-strong)] px-3 py-2 disabled:opacity-40">Next</button>
          </div>
        </div>
      </div>
    </main>
  );
}
