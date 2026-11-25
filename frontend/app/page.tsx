"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/auth-provider";

export default function HomePage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    router.replace(user ? "/workspaces" : "/login");
  }, [loading, router, user]);

  return (
    <main className="grid min-h-screen place-items-center bg-[var(--background)]">
      <div className="flex items-center gap-3 text-sm text-[var(--muted)]">
        <div className="grid size-8 place-items-center rounded-lg bg-[var(--accent)] text-xs font-bold text-[var(--accent-foreground)]">PL</div>
        Loading PyLake
      </div>
    </main>
  );
}
