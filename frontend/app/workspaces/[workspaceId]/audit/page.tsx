"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";

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
    <main className="min-h-screen px-6 py-8 md:px-10">
      <div className="mx-auto max-w-6xl">
        <Link href={`/workspaces/${workspaceId}`} className="text-sm text-[#98a0b3]">Back to workspace</Link>
        <h1 className="mt-2 text-3xl font-semibold">Audit log</h1>
        {error && <div className="mt-5 rounded-md border border-red-900 bg-red-950/40 px-4 py-3 text-sm text-red-300">{error}</div>}
        <div className="mt-6 overflow-hidden rounded-lg border border-[#242936]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[#11141b] text-[#98a0b3]">
              <tr><th className="px-4 py-3">Action</th><th className="px-4 py-3">Target</th><th className="px-4 py-3">Time</th></tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} className="border-t border-[#242936]">
                  <td className="px-4 py-3">{item.action}</td>
                  <td className="px-4 py-3 font-mono text-xs text-[#98a0b3]">{item.target_type}:{item.target_id ?? "-"}</td>
                  <td className="px-4 py-3 text-[#98a0b3]">{new Date(item.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {items.length === 0 && !error && <p className="mt-5 text-sm text-[#98a0b3]">No audit events.</p>}
        <div className="mt-4 flex items-center justify-between text-sm text-[#98a0b3]">
          <span>{total} events</span>
          <div className="flex gap-2">
            <button disabled={page === 1} onClick={() => setPage((value) => value - 1)} className="rounded border border-[#303646] px-3 py-2 disabled:opacity-40">Previous</button>
            <button disabled={page * 25 >= total} onClick={() => setPage((value) => value + 1)} className="rounded border border-[#303646] px-3 py-2 disabled:opacity-40">Next</button>
          </div>
        </div>
      </div>
    </main>
  );
}
