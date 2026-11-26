"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAuth, User } from "@/components/auth-provider";
import { PyLakeLogo } from "@/components/pylake-brand";
import { useTheme } from "@/components/theme-provider";

export default function LoginPage() {
  const router = useRouter();
  const { refresh } = useAuth();
  const { theme } = useTheme();
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
    <main className="grid min-h-screen place-items-center px-6 bg-[var(--background)]">
      <Link href="/" className="fixed left-6 top-6" aria-label="PyLake home">
        <PyLakeLogo size={34} theme={theme} />
      </Link>
      <form onSubmit={submit} className="w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--surface)] p-8 shadow-[var(--shadow-soft)]">
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-[var(--accent)]">Welcome back</p>
        <h1 className="mt-2 text-2xl font-semibold">Sign in to PyLake</h1>
        <p className="mt-2 text-sm text-[var(--muted)]">Access your lakehouse and data workspaces.</p>
        {error && <div className="mt-5 rounded-lg border border-[color-mix(in_srgb,var(--danger)_35%,transparent)] bg-[color-mix(in_srgb,var(--danger)_8%,var(--surface))] px-3 py-2.5 text-sm text-[var(--danger)]">{error}</div>}
        <label className="mt-6 block text-sm">Email
          <input required type="email" value={email} onChange={(event) => setEmail(event.target.value)}
            className="mt-2 h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-3 outline-none focus:border-[var(--accent)]" />
        </label>
        <label className="mt-4 block text-sm">Password
          <input required type="password" value={password} onChange={(event) => setPassword(event.target.value)}
            className="mt-2 h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-3 outline-none focus:border-[var(--accent)]" />
        </label>
        <button disabled={loading} className="mt-6 h-11 w-full rounded-lg bg-[var(--accent)] font-medium text-[var(--accent-foreground)] disabled:opacity-60">
          {loading ? "Signing in..." : "Sign in"}
        </button>
        <p className="mt-5 text-center text-sm text-[var(--muted)]">
          New to PyLake? <Link className="text-[var(--accent)]" href="/register">Create account</Link>
        </p>
      </form>
    </main>
  );
}
