"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";

export type User = {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  created_at: string;
};

type AuthContextValue = {
  user: User | null;
  loading: boolean;
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue>({
  user: null,
  loading: true,
  refresh: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [authInitialized, setAuthInitialized] = useState(false);
  const pathname = usePathname();
  const router = useRouter();

  const refresh = useCallback(async () => {
    setLoading(true);
    const result = await api<User>("/api/v1/auth/me");
    setUser(result.data ?? null);
    setLoading(false);
    setAuthInitialized(true);
  }, []);

  useEffect(() => {
    if (pathname === "/" || authInitialized) return;
    const timeout = window.setTimeout(() => {
      void refresh();
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [authInitialized, pathname, refresh]);

  useEffect(() => {
    if (loading) return;
    const publicRoute = pathname === "/" || pathname === "/login" || pathname === "/register";
    const authRoute = pathname === "/login" || pathname === "/register";
    if (!user && !publicRoute) router.replace("/login");
    if (user && authRoute) router.replace("/workspaces");
  }, [loading, pathname, router, user]);

  return (
    <AuthContext.Provider value={{ user, loading, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
