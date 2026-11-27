import type { TrustMetric } from "./types";

export function TrustMetricCard({ name, metric }: { name: string; metric: TrustMetric }) {
  const label = name.replaceAll("_", " ");
  return (
    <article className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold capitalize">{label}</h3>
        <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${metric.status === "MEASURED" ? "border-[color-mix(in_srgb,var(--accent)_35%,transparent)] text-[var(--accent)]" : "border-[var(--border-strong)] text-[var(--muted)]"}`}>
          {metric.status === "MEASURED" ? "MEASURED" : "NOT MEASURED"}
        </span>
      </div>
      {metric.status === "MEASURED" && metric.score !== null ? (
        <p className="mt-3 text-2xl font-semibold tabular-nums">{metric.score.toFixed(1)}<span className="ml-1 text-sm text-[var(--muted)]">/100</span></p>
      ) : <p className="mt-3 text-sm text-[var(--muted)]">Score not shown</p>}
      <p className="mt-2 text-xs leading-5 text-[var(--foreground)]">{metric.detail}</p>
      <p className="mt-2 text-[11px] leading-4 text-[var(--muted)]"><span className="font-medium">Basis:</span> {metric.basis}</p>
    </article>
  );
}
