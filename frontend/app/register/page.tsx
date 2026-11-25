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
    <main className="grid min-h-screen place-items-center px-6">
      <form onSubmit={submit} className="w-full max-w-md rounded-xl border border-[#242936] bg-[#11141b] p-8">
        <h1 className="text-2xl font-semibold">Create your account</h1>
        <p className="mt-2 text-sm text-[#98a0b3]">Start your PyLake workspace.</p>
        {error && <div className="mt-5 rounded-md border border-red-900 bg-red-950/40 px-3 py-2 text-sm text-red-300">{error}</div>}
        <label className="mt-6 block text-sm">Full name
          <input required value={fullName} onChange={(event) => setFullName(event.target.value)}
            className="mt-2 h-11 w-full rounded-md border border-[#303646] bg-[#0b0d12] px-3 outline-none focus:border-[#7dd3fc]" />
        </label>
        <label className="mt-4 block text-sm">Email
          <input required type="email" value={email} onChange={(event) => setEmail(event.target.value)}
            className="mt-2 h-11 w-full rounded-md border border-[#303646] bg-[#0b0d12] px-3 outline-none focus:border-[#7dd3fc]" />
        </label>
        <label className="mt-4 block text-sm">Password
          <input required type="password" minLength={12} value={password} onChange={(event) => setPassword(event.target.value)}
            className="mt-2 h-11 w-full rounded-md border border-[#303646] bg-[#0b0d12] px-3 outline-none focus:border-[#7dd3fc]" />
        </label>
        <button disabled={loading} className="mt-6 h-11 w-full rounded-md bg-[#7dd3fc] font-medium text-[#071018] disabled:opacity-60">
          {loading ? "Creating account..." : "Create account"}
        </button>
        <p className="mt-5 text-center text-sm text-[#98a0b3]">
          Already have an account? <Link className="text-[#7dd3fc]" href="/login">Sign in</Link>
        </p>
      </form>
    </main>
  );
}
