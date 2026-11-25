"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { Plus, X } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";

type Workspace = {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  owner_id: string;
};

export default function WorkspacesPage() {
  const { user, loading } = useAuth();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [error, setError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");

  const load = async () => {
    const result = await api<Workspace[]>("/api/v1/workspaces");
    if (result.error) setError(result.error);
    else setWorkspaces(result.data ?? []);
  };

  useEffect(() => {
    if (!user) return;
    const timeout = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [user]);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    const result = await api<Workspace>("/api/v1/workspaces", {
      method: "POST",
      body: JSON.stringify({ name, slug, description: description || null }),
    });
    if (result.error) {
      setError(result.error);
      return;
    }
    setCreateOpen(false);
    setName("");
    setSlug("");
    setDescription("");
    await load();
  };

  if (loading) return <main className="p-8 text-[#98a0b3]">Loading workspace...</main>;

  return (
    <main className="min-h-[calc(100vh-64px)] px-4 py-8 md:px-7 lg:px-8">
      <div className="mx-auto max-w-6xl">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-[#98a0b3]">{user?.email}</p>
            <h1 className="mt-1 text-3xl font-semibold">Workspaces</h1>
          </div>
          <button onClick={() => setCreateOpen(true)} className="flex h-10 items-center gap-2 rounded-lg bg-[var(--accent)] px-4 text-sm font-medium text-[var(--accent-foreground)]">
            <Plus size={16} /> New workspace
          </button>
        </div>

        {error && <div className="mt-6 rounded-md border border-red-900 bg-red-950/40 px-4 py-3 text-sm text-red-300">{error}</div>}

        {workspaces.length === 0 ? (
          <div className="mt-8 rounded-xl border border-dashed border-[var(--border)] bg-[var(--surface)] p-10 text-center">
            <p className="font-medium">No workspaces yet</p>
            <p className="mt-2 text-sm text-[#98a0b3]">Create your first workspace to organize data and pipelines.</p>
          </div>
        ) : (
          <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {workspaces.map((workspace) => (
              <Link key={workspace.id} href={`/workspaces/${workspace.id}`}
                className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 transition-colors hover:border-[var(--border-strong)]">
                <p className="font-medium">{workspace.name}</p>
                <p className="mt-1 text-sm text-[#98a0b3]">{workspace.slug}</p>
                {workspace.description && <p className="mt-4 text-sm text-[#98a0b3]">{workspace.description}</p>}
              </Link>
            ))}
          </div>
        )}
      </div>

      {createOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 px-6">
          <form onSubmit={create} className="w-full max-w-lg rounded-xl border border-[#303646] bg-[#11141b] p-6">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">Create workspace</h2>
              <button type="button" onClick={() => setCreateOpen(false)} aria-label="Close"><X size={18} /></button>
            </div>
            <label className="mt-6 block text-sm">Name
              <input required value={name} onChange={(event) => setName(event.target.value)}
                className="mt-2 h-11 w-full rounded-md border border-[#303646] bg-[#0b0d12] px-3 outline-none focus:border-[#7dd3fc]" />
            </label>
            <label className="mt-4 block text-sm">Slug
              <input required pattern="[a-z0-9]+(?:-[a-z0-9]+)*" value={slug} onChange={(event) => setSlug(event.target.value.toLowerCase())}
                className="mt-2 h-11 w-full rounded-md border border-[#303646] bg-[#0b0d12] px-3 outline-none focus:border-[#7dd3fc]" />
            </label>
            <label className="mt-4 block text-sm">Description
              <textarea value={description} onChange={(event) => setDescription(event.target.value)}
                className="mt-2 min-h-24 w-full rounded-md border border-[#303646] bg-[#0b0d12] p-3 outline-none focus:border-[#7dd3fc]" />
            </label>
            <div className="mt-6 flex justify-end gap-3">
              <button type="button" onClick={() => setCreateOpen(false)} className="h-10 rounded-md px-4 text-sm text-[#98a0b3]">Cancel</button>
              <button className="h-10 rounded-md bg-[#7dd3fc] px-4 text-sm font-medium text-[#071018]">Create workspace</button>
            </div>
          </form>
        </div>
      )}
    </main>
  );
}
