"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  BarChart3,
  Bell,
  Braces,
  ChevronDown,
  Database,
  FolderKanban,
  LayoutDashboard,
  Menu,
  Moon,
  Search,
  Settings,
  ScrollText,
  Sparkles,
  Sun,
  Workflow,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { useTheme } from "@/components/theme-provider";
import { AICopilotChat } from "@/components/ai-copilot-chat";
import {
  AIPageContextProvider,
  useCurrentAIPageContext,
} from "@/components/ai-page-context";

type Workspace = {
  id: string;
  name: string;
  slug: string;
};

const navigation = [
  { label: "Overview", href: "overview", icon: LayoutDashboard },
  { label: "Data Explorer", href: "data", icon: Database },
  { label: "Lakehouse", href: "lakehouse", icon: FolderKanban },
  { label: "SQL Workspace", href: "sql", icon: Braces },
  { label: "AI Copilot", href: "ai", icon: Sparkles },
  { label: "Pipelines", href: "pipelines", icon: Workflow },
  { label: "Data Catalog", href: "catalog", icon: Search },
  { label: "Monitoring", href: "pipelines", icon: BarChart3 },
  { label: "Audit Logs", href: "audit", icon: ScrollText },
  { label: "Workspace Settings", href: "settings", icon: Settings },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <AIPageContextProvider>
      <AppShellContent>{children}</AppShellContent>
    </AIPageContextProvider>
  );
}

function AppShellContent({ children }: { children: React.ReactNode }) {
  const { user, loading, refresh } = useAuth();
  const pathname = usePathname();
  const aiPageContext = useCurrentAIPageContext(pathname);
  const router = useRouter();
  const { theme, setTheme } = useTheme();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceMenu, setWorkspaceMenu] = useState(false);
  const [userMenu, setUserMenu] = useState(false);
  const [aiPanelOpen, setAiPanelOpen] = useState(false);

  const workspaceId = (() => {
    const match = pathname.match(/^\/workspaces\/([^/]+)/);
    return match?.[1] ?? null;
  })();
  const currentWorkspace = workspaces.find((item) => item.id === workspaceId);
  const publicRoute = pathname === "/login" || pathname === "/register";
  const workspaceRoute = pathname.startsWith("/workspaces/");

  useEffect(() => {
    if (!user) return;
    api<Workspace[]>("/api/v1/workspaces").then((result) => {
      setWorkspaces(result.data ?? []);
    });
  }, [user]);

  useEffect(() => {
    const timeout = window.setTimeout(() => setMobileOpen(false), 0);
    return () => window.clearTimeout(timeout);
  }, [pathname]);

  if (publicRoute || pathname === "/") {
    return <>{children}</>;
  }
  if (loading) {
    return <main className="grid min-h-screen place-items-center bg-[var(--background)] text-[var(--muted)]">Loading PyLake...</main>;
  }
  if (!user) return <>{children}</>;

  const pageTitle = navigation.find((item) =>
    workspaceId
      ? item.href === "overview"
        ? pathname === `/workspaces/${workspaceId}`
        : pathname.includes(`/${item.href}`)
      : false,
  )?.label ?? "PyLake";

  const logout = async () => {
    await api("/api/v1/auth/logout", { method: "POST" });
    await refresh();
  };

  return (
    <div className="min-h-screen bg-[var(--background)] text-[var(--foreground)]">
      {mobileOpen && (
        <button
          aria-label="Close navigation"
          className="fixed inset-0 z-40 bg-black/50 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside
        className={`fixed bottom-0 left-0 top-0 z-50 flex flex-col border-r border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-soft)] transition-[width,transform] duration-200 motion-reduce:transition-none ${
          collapsed ? "w-[72px]" : "w-[248px]"
        } ${mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"}`}
      >
        <div className={`flex h-16 items-center border-b border-[var(--border)] ${collapsed ? "justify-center" : "justify-between px-4"}`}>
          <Link href="/workspaces" className="flex items-center gap-2.5" aria-label="PyLake workspaces">
            <div className="grid size-8 shrink-0 place-items-center rounded-lg border border-[color-mix(in_srgb,var(--accent)_45%,var(--border))] bg-[var(--accent-soft)] text-[11px] font-semibold tracking-wide text-[var(--accent)]">PL</div>
            {!collapsed && <span className="text-[15px] font-semibold tracking-tight">PyLake<span className="ml-2 text-[9px] font-medium uppercase tracking-[0.18em] text-[var(--muted)]">Lakehouse</span></span>}
          </Link>
          {!collapsed && (
            <button className="hidden size-8 place-items-center rounded-md text-[var(--muted)] hover:bg-[var(--surface-hover)] lg:grid" onClick={() => setCollapsed(true)} aria-label="Collapse sidebar">
              <X size={15} />
            </button>
          )}
        </div>

        {workspaceId && (
          <div className="relative px-2 py-3">
            <button
              onClick={() => setWorkspaceMenu((value) => !value)}
              className={`flex h-10 w-full items-center rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] hover:border-[var(--border-strong)] ${collapsed ? "justify-center" : "justify-between px-3"}`}
            >
              {!collapsed && (
                <>
                  <span className="min-w-0 truncate text-sm">{currentWorkspace?.name ?? "Workspace"}</span>
                  <ChevronDown size={14} className="text-[var(--muted)]" />
                </>
              )}
              {collapsed && <Database size={16} />}
            </button>
            {workspaceMenu && !collapsed && (
              <div className="absolute left-2 right-2 top-14 z-20 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-1.5 shadow-xl">
                {workspaces.map((workspace) => (
                  <button
                    key={workspace.id}
                    onClick={() => {
                      setWorkspaceMenu(false);
                      router.push(`/workspaces/${workspace.id}`);
                    }}
                    className="flex h-9 w-full items-center rounded-md px-2.5 text-left text-sm hover:bg-[var(--surface-hover)]"
                  >
                    {workspace.name}
                  </button>
                ))}
                <Link href="/workspaces" className="mt-1 flex h-9 items-center rounded-md px-2.5 text-sm text-[var(--muted)] hover:bg-[var(--surface-hover)]">
                  Manage workspaces
                </Link>
              </div>
            )}
          </div>
        )}

        {workspaceId && (
          <nav className="scrollbar-thin flex-1 overflow-y-auto px-2 pb-3" aria-label="Workspace navigation">
            {navigation.map((item) => {
              const Icon = item.icon;
              const href = item.href === "overview"
                ? `/workspaces/${workspaceId}`
                : item.href === "settings"
                  ? `/workspaces/${workspaceId}`
                  : `/workspaces/${workspaceId}/${item.href}`;
              const active = item.href === "overview"
                ? pathname === `/workspaces/${workspaceId}`
                : pathname.includes(`/${item.href}`);
              return (
                <Link
                  key={item.label}
                  href={href}
                  title={collapsed ? item.label : undefined}
                  className={`mb-1 flex h-9 items-center rounded-md text-sm transition-colors ${collapsed ? "justify-center" : "gap-3 px-3"} ${
                    active
                      ? "bg-[var(--accent-soft)] text-[var(--foreground)]"
                      : "text-[var(--muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--foreground)]"
                  }`}
                >
                  <Icon size={17} strokeWidth={1.8} />
                  {!collapsed && <span>{item.label}</span>}
                </Link>
              );
            })}
          </nav>
        )}

        {collapsed && (
          <button onClick={() => setCollapsed(false)} className="mx-auto mb-3 grid size-9 place-items-center rounded-md text-[var(--muted)] hover:bg-[var(--surface-hover)]" aria-label="Expand sidebar">
            <Menu size={16} />
          </button>
        )}
      </aside>

      <div className={`transition-[margin] duration-200 ${collapsed ? "lg:ml-[72px]" : "lg:ml-[248px]"}`}>
        <header className="sticky top-0 z-30 flex h-16 items-center border-b border-[var(--border)] bg-[color-mix(in_srgb,var(--background)_92%,transparent)] px-4 backdrop-blur-xl md:px-6">
          <button className="mr-3 grid size-9 place-items-center rounded-md border border-[var(--border)] lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open navigation">
            <Menu size={18} />
          </button>
          <div className="min-w-0">
            {currentWorkspace && <p className="truncate text-xs text-[var(--muted)]">{currentWorkspace.name}</p>}
            <h1 className="truncate text-sm font-semibold">{pageTitle}</h1>
          </div>
          <div className="ml-auto flex items-center gap-1.5">
            {workspaceId && (
              <button className="hidden h-9 w-52 items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm text-[var(--muted)] md:flex">
                <Search size={15} />
                <span className="flex-1 text-left">Search...</span>
                <kbd className="rounded border border-[var(--border)] px-1.5 py-0.5 text-[10px]">⌘K</kbd>
              </button>
            )}
            {workspaceId && (
              <button
                onClick={() => setAiPanelOpen((value) => !value)}
                aria-expanded={aiPanelOpen}
                aria-label={aiPanelOpen ? "Close AI Copilot" : "Open AI Copilot"}
                className={`grid size-9 place-items-center rounded-md transition-colors ${aiPanelOpen ? "bg-[var(--accent-soft)] text-[var(--accent)]" : "text-[var(--muted)] hover:bg-[var(--surface-hover)]"}`}
              >
                <Sparkles size={16} />
              </button>
            )}
            <button
              className="grid size-9 place-items-center rounded-md text-[var(--muted)] hover:bg-[var(--surface-hover)]"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              aria-label="Toggle theme"
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            <button className="relative grid size-9 place-items-center rounded-md text-[var(--muted)] hover:bg-[var(--surface-hover)]" aria-label="Notifications">
              <Bell size={16} />
              <span className="absolute right-2 top-2 size-1.5 rounded-full bg-[var(--accent)]" />
            </button>
            <div className="relative">
              <button onClick={() => setUserMenu((value) => !value)} className="ml-1 flex h-9 items-center gap-2 rounded-md px-1.5 hover:bg-[var(--surface-hover)]">
                <div className="grid size-7 place-items-center rounded-full border border-[color-mix(in_srgb,var(--accent)_35%,var(--border))] bg-[var(--accent-soft)] text-xs font-semibold text-[var(--accent)]">{user.full_name?.slice(0, 1).toUpperCase()}</div>
              </button>
              {userMenu && (
                <div className="absolute right-0 top-11 w-56 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-2 shadow-xl">
                  <div className="border-b border-[var(--border)] px-2 pb-2">
                    <p className="truncate text-sm font-medium">{user.full_name}</p>
                    <p className="truncate text-xs text-[var(--muted)]">{user.email}</p>
                  </div>
                  <button onClick={logout} className="mt-1 h-9 w-full rounded-md px-2 text-left text-sm hover:bg-[var(--surface-hover)]">Sign out</button>
                </div>
              )}
            </div>
          </div>
        </header>
        <div className="min-w-0">{children}</div>
      </div>
      {workspaceId && aiPanelOpen && (
        <section aria-label="AI Copilot panel" className="fixed bottom-4 right-4 z-[60] w-[min(100vw-2rem,440px)] overflow-hidden rounded-xl border border-[var(--border-strong)] bg-[var(--background)] shadow-2xl">
          <div className="flex h-11 items-center justify-between border-b border-[var(--border)] bg-[var(--surface)] px-3">
            <p className="flex items-center gap-2 text-xs font-semibold"><Sparkles size={14} className="text-[var(--accent)]" /> PyLake AI Copilot</p>
            <div className="flex items-center gap-3">
              <Link href={`/workspaces/${workspaceId}/ai`} onClick={() => setAiPanelOpen(false)} className="text-[10px] text-[var(--muted)] hover:text-[var(--accent)]">Open full page</Link>
              <button onClick={() => setAiPanelOpen(false)} aria-label="Close AI Copilot" className="text-xs text-[var(--muted)] hover:text-[var(--foreground)]">Close</button>
            </div>
          </div>
          <AICopilotChat workspaceId={workspaceId} compact pageContext={aiPageContext} />
        </section>
      )}
    </div>
  );
}
