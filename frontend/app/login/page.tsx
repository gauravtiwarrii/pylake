"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAuth, User } from "@/components/auth-provider";

export default function LoginPage() {
  const router = useRouter();
  const { refresh } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    const result = await api<User>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setLoading(false);
    if (result.error) {
      setError(result.error);
      return;
    }
    await refresh();
    router.replace("/workspaces");
  };

  return (
    <main className="grid min-h-screen place-items-center px-6">
      <form onSubmit={submit} className="w-full max-w-md rounded-xl border border-[#242936] bg-[#11141b] p-8">
        <h1 className="text-2xl font-semibold">Sign in to PyLake</h1>
        <p className="mt-2 text-sm text-[#98a0b3]">Access your data workspaces.</p>
        {error && <div className="mt-5 rounded-md border border-red-900 bg-red-950/40 px-3 py-2 text-sm text-red-300">{error}</div>}
        <label className="mt-6 block text-sm">Email
          <input required type="email" value={email} onChange={(event) => setEmail(event.target.value)}
            className="mt-2 h-11 w-full rounded-md border border-[#303646] bg-[#0b0d12] px-3 outline-none focus:border-[#7dd3fc]" />
        </label>
        <label className="mt-4 block text-sm">Password
          <input required type="password" value={password} onChange={(event) => setPassword(event.target.value)}
            className="mt-2 h-11 w-full rounded-md border border-[#303646] bg-[#0b0d12] px-3 outline-none focus:border-[#7dd3fc]" />
        </label>
        <button disabled={loading} className="mt-6 h-11 w-full rounded-md bg-[#7dd3fc] font-medium text-[#071018] disabled:opacity-60">
          {loading ? "Signing in..." : "Sign in"}
        </button>
        <p className="mt-5 text-center text-sm text-[#98a0b3]">
          New to PyLake? <Link className="text-[#7dd3fc]" href="/register">Create account</Link>
        </p>
      </form>
    </main>
  );
}
