"use client";

import { use, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";

type Workspace = {
  id: string;
  name: string;
  slug: string;
  description: string | null;
};

type Member = {
  id: string;
  user_id: string;
  role: "OWNER" | "ADMIN" | "EDITOR" | "VIEWER";
};

export default function WorkspaceDetailPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = use(params);
  const { user } = useAuth();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"ADMIN" | "EDITOR" | "VIEWER">("VIEWER");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const [workspaceResult, memberResult] = await Promise.all([
      api<Workspace>(`/api/v1/workspaces/${workspaceId}`),
      api<Member[]>(`/api/v1/workspaces/${workspaceId}/members`),
    ]);
    if (workspaceResult.error) setError(workspaceResult.error);
    else setWorkspace(workspaceResult.data ?? null);
    if (memberResult.error) setError(memberResult.error);
    else setMembers(memberResult.data ?? []);
  }, [workspaceId]);

  useEffect(() => {
    if (!user) return;
    const timeout = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [load, user]);

  const addMember = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    const result = await api<Member>(`/api/v1/workspaces/${workspaceId}/members`, {
      method: "POST",
      body: JSON.stringify({ email, role }),
    });
    if (result.error) {
      setError(result.error);
      return;
    }
    setEmail("");
    await load();
  };

  const changeRole = async (memberId: string, nextRole: Member["role"]) => {
    setError("");
    const result = await api<Member>(
      `/api/v1/workspaces/${workspaceId}/members/${memberId}`,
      {
        method: "PATCH",
        body: JSON.stringify({ role: nextRole }),
      },
    );
    if (result.error) setError(result.error);
    else await load();
  };

  const removeMember = async (memberId: string) => {
    setError("");
    const result = await api(
      `/api/v1/workspaces/${workspaceId}/members/${memberId}`,
      { method: "DELETE" },
    );
    if (result.error) setError(result.error);
    else await load();
  };

  if (!workspace) {
    return <main className="p-8">{error || "Loading workspace..."}</main>;
  }

  return (
    <main className="min-h-screen px-6 py-8 md:px-10">
      <div className="mx-auto max-w-5xl">
        <p className="text-sm text-[#98a0b3]">{workspace.slug}</p>
        <h1 className="mt-1 text-3xl font-semibold">{workspace.name}</h1>
        {workspace.description && (
          <p className="mt-3 text-[#98a0b3]">{workspace.description}</p>
        )}
        <a
          href={`/workspaces/${workspaceId}/data`}
          className="mt-5 inline-flex h-10 items-center rounded-md border border-[#303646] px-4 text-sm"
        >
          Open Data Explorer
        </a>
        <a
          href={`/workspaces/${workspaceId}/lakehouse`}
          className="ml-3 mt-5 inline-flex h-10 items-center rounded-md border border-[#303646] px-4 text-sm"
        >
          Open Lakehouse
        </a>
        <a
          href={`/workspaces/${workspaceId}/sql`}
          className="ml-3 mt-5 inline-flex h-10 items-center rounded-md border border-[#303646] px-4 text-sm"
        >
          Open SQL Editor
        </a>
        <a
          href={`/workspaces/${workspaceId}/pipelines`}
          className="ml-3 mt-5 inline-flex h-10 items-center rounded-md border border-[#303646] px-4 text-sm"
        >
          Open Pipelines
        </a>

        {error && (
          <div className="mt-6 rounded-md border border-red-900 bg-red-950/40 px-4 py-3 text-sm text-red-300">
            {error}
          </div>
        )}

        <section className="mt-8 rounded-lg border border-[#242936] bg-[#11141b] p-5">
          <h2 className="font-medium">Members</h2>
          <form onSubmit={addMember} className="mt-5 flex flex-col gap-3 md:flex-row">
            <input
              required
              type="email"
              placeholder="member@example.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="h-10 flex-1 rounded-md border border-[#303646] bg-[#0b0d12] px-3 text-sm outline-none focus:border-[#7dd3fc]"
            />
            <select
              value={role}
              onChange={(event) =>
                setRole(event.target.value as "ADMIN" | "EDITOR" | "VIEWER")
              }
              className="h-10 rounded-md border border-[#303646] bg-[#0b0d12] px-3 text-sm"
            >
              <option value="VIEWER">Viewer</option>
              <option value="EDITOR">Editor</option>
              <option value="ADMIN">Admin</option>
            </select>
            <button className="h-10 rounded-md bg-[#7dd3fc] px-4 text-sm font-medium text-[#071018]">
              Add member
            </button>
          </form>

          <div className="mt-5 divide-y divide-[#242936]">
            {members.map((member) => (
              <div key={member.id} className="flex items-center justify-between py-3">
                <div>
                  <p className="font-mono text-xs text-[#98a0b3]">{member.user_id}</p>
                </div>
                {member.role === "OWNER" ? (
                  <span className="text-sm text-[#98a0b3]">Owner</span>
                ) : (
                  <div className="flex items-center gap-2">
                    <select
                      value={member.role}
                      onChange={(event) =>
                        changeRole(
                          member.id,
                          event.target.value as "ADMIN" | "EDITOR" | "VIEWER",
                        )
                      }
                      className="h-9 rounded-md border border-[#303646] bg-[#0b0d12] px-2 text-sm"
                    >
                      <option value="VIEWER">Viewer</option>
                      <option value="EDITOR">Editor</option>
                      <option value="ADMIN">Admin</option>
                    </select>
                    <button
                      onClick={() => removeMember(member.id)}
                      className="h-9 rounded-md border border-[#513036] px-3 text-sm text-red-300"
                    >
                      Remove
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
