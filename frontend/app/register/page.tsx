"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { PyLakeLogo } from "@/components/pylake-brand";
import { useTheme } from "@/components/theme-provider";

export default function RegisterPage() {
  const router = useRouter();
  const { theme } = useTheme();
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
      <Link href="/" className="fixed left-6 top-6" aria-label="PyLake home">
        <PyLakeLogo size={34} theme={theme} />
      </Link>
      <form onSubmit={submit} className="w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--surface)] p-8 shadow-[var(--shadow-soft)]">
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-[var(--accent)]">Get started</p>
        <h1 className="text-2xl font-semibold">Create your account</h1>
        <p className="mt-2 text-sm text-[var(--muted)]">Create and manage data workspaces.</p>
        {error && <div className="mt-5 rounded-lg border border-[color-mix(in_srgb,var(--danger)_35%,transparent)] bg-[color-mix(in_srgb,var(--danger)_8%,var(--surface))] px-3 py-2 text-sm text-[var(--danger)]">{error}</div>}
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
        <p className="mt-5 text-center text-sm text-[var(--muted)]">
          Already have an account? <Link className="text-[var(--accent)] hover:text-[var(--accent-strong)]" href="/login">Sign in</Link>
        </p>
      </form>
    </main>
  );
}
