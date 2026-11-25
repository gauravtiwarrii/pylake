import {
  Braces,
  Database,
  LayoutDashboard,
  Settings,
  Workflow,
} from "lucide-react";

const navigation = [
  { label: "Overview", icon: LayoutDashboard, active: true },
  { label: "Data Explorer", icon: Database },
  { label: "SQL Editor", icon: Braces },
  { label: "Pipelines", icon: Workflow },
  { label: "Settings", icon: Settings },
];

export default function Home() {
  return (
    <main className="min-h-screen bg-[#090b10] text-[#f4f6f8]">
      <aside className="fixed bottom-0 left-0 top-0 w-60 border-r border-[#242936] bg-[#0d1016] p-4">
        <div className="mb-8 flex h-10 items-center gap-3 px-2">
          <div className="grid size-8 place-items-center rounded-lg bg-[#7dd3fc] text-sm font-bold text-[#071018]">
            PL
          </div>
          <span className="text-lg font-semibold tracking-tight">PyLake</span>
        </div>
        <nav className="space-y-1" aria-label="Main navigation">
          {navigation.map(({ label, icon: Icon, active }) => (
            <div
              key={label}
              className={`flex h-10 items-center gap-3 rounded-md px-3 text-sm ${
                active
                  ? "bg-[#191d27] text-white"
                  : "text-[#98a0b3]"
              }`}
            >
              <Icon size={17} aria-hidden="true" />
              {label}
            </div>
          ))}
        </nav>
      </aside>

      <section className="ml-60 min-h-screen p-8">
        <div className="mx-auto max-w-6xl">
          <div className="mb-8 flex items-end justify-between">
            <div>
              <p className="mb-2 text-sm text-[#98a0b3]">Local workspace</p>
              <h1 className="text-3xl font-semibold tracking-tight">Overview</h1>
            </div>
            <span className="rounded-full border border-[#27533c] bg-[#102118] px-3 py-1 text-xs text-[#86efac]">
              Backend starting
            </span>
          </div>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {[
              ["Datasets", "0"],
              ["Records", "0"],
              ["Storage", "0 B"],
              ["Pipeline runs", "0"],
            ].map(([label, value]) => (
              <article
                key={label}
                className="rounded-lg border border-[#242936] bg-[#11141b] p-5"
              >
                <p className="text-sm text-[#98a0b3]">{label}</p>
                <p className="mt-3 text-2xl font-semibold">{value}</p>
              </article>
            ))}
          </div>

          <div className="mt-4 rounded-lg border border-[#242936] bg-[#11141b] p-6">
            <h2 className="font-medium">Getting started</h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-[#98a0b3]">
              PyLake is initialized. Connect the backend and begin by adding
              workspaces and datasets in the next milestone.
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}
