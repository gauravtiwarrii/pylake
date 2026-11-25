"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    if (password.length < 12) {
      setError("Password must be at least 12 characters.");
      return;
    }
    setLoading(true);
    const result = await api("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify({ full_name: fullName, email, password }),
    });
    setLoading(false);
    if (result.error) {
      setError(result.error);
      return;
    }
    router.replace("/login");
  };

  return (
    <main className="grid min-h-screen place-items-center px-6 bg-[var(--background)]">
      <div className="fixed left-6 top-6 flex items-center gap-2.5">
        <div className="grid size-8 place-items-center rounded-lg bg-[var(--accent)] text-xs font-bold text-[var(--accent-foreground)]">PL</div>
        <span className="font-semibold">PyLake</span>
      </div>
      <form onSubmit={submit} className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-8 shadow-[0_20px_60px_rgba(0,0,0,.16)]">
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-[var(--accent)]">Get started</p>
        <h1 className="text-2xl font-semibold">Create your account</h1>
        <p className="mt-2 text-sm text-[var(--muted)]">Create and manage data workspaces.</p>
        {error && <div className="mt-5 rounded-md border border-red-900 bg-red-950/40 px-3 py-2 text-sm text-red-300">{error}</div>}
        <label className="mt-6 block text-sm">Full name
          <input required value={fullName} onChange={(event) => setFullName(event.target.value)}
            className="mt-2 h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-3 outline-none focus:border-[var(--accent)]" />
        </label>
        <label className="mt-4 block text-sm">Email
          <input required type="email" value={email} onChange={(event) => setEmail(event.target.value)}
            className="mt-2 h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-3 outline-none focus:border-[var(--accent)]" />
        </label>
        <label className="mt-4 block text-sm">Password
          <input required type="password" minLength={12} value={password} onChange={(event) => setPassword(event.target.value)}
            className="mt-2 h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-3 outline-none focus:border-[var(--accent)]" />
        </label>
        <button disabled={loading} className="mt-6 h-11 w-full rounded-lg bg-[var(--accent)] font-medium text-[var(--accent-foreground)] disabled:opacity-60">
          {loading ? "Creating account..." : "Create account"}
        </button>
        <p className="mt-5 text-center text-sm text-[#98a0b3]">
          Already have an account? <Link className="text-[#7dd3fc]" href="/login">Sign in</Link>
        </p>
      </form>
    </main>
  );
}
