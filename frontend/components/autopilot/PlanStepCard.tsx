import { RiskBadge } from "./RiskBadge";
import type { PlanStep } from "./types";

export function PlanStepCard({ step }: { step: PlanStep }) {
  return (
    <article className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-[var(--shadow-soft)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="grid size-7 shrink-0 place-items-center rounded-full border border-[var(--border-strong)] bg-[var(--surface-raised)] text-xs font-semibold text-[var(--muted)]">
            {step.step_order}
          </span>
          <div className="min-w-0">
            <h3 className="font-medium">{step.title}</h3>
            <p className="mt-1 font-mono text-[11px] text-[var(--accent)]">{step.action_key}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <RiskBadge risk={step.risk_level} />
          <span className="rounded-full border border-[var(--border)] px-2 py-0.5 text-[10px] text-[var(--muted)]">{step.status}</span>
        </div>
      </div>

      {step.rationale && <p className="mt-3 text-sm leading-6 text-[var(--muted)]">{step.rationale}</p>}
      {step.evidence_json?.length ? (
        <div className="mt-3">
          <h4 className="text-[10px] font-semibold uppercase tracking-wider text-[var(--muted)]">Evidence</h4>
          <ul className="mt-1 space-y-1">
            {step.evidence_json.map((item, index) => (
              <li key={`${item.source ?? "evidence"}-${index}`} className="text-xs leading-5 text-[var(--muted)]">
                {item.source && <span className="font-medium text-[var(--foreground)]">{item.source}: </span>}{item.detail}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <details className="mt-3 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)]">
        <summary className="cursor-pointer px-3 py-2 text-xs font-medium">Arguments</summary>
        <pre className="overflow-x-auto border-t border-[var(--border)] px-3 py-2 font-mono text-[11px] leading-5 text-[var(--muted)]">{JSON.stringify(step.arguments_json, null, 2)}</pre>
      </details>

      {step.preview_json && (
        <details className="mt-2 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)]" open>
          <summary className="cursor-pointer px-3 py-2 text-xs font-medium">Preview</summary>
          <pre className="overflow-x-auto border-t border-[var(--border)] px-3 py-2 font-mono text-[11px] leading-5 text-[var(--muted)]">{JSON.stringify(step.preview_json, null, 2)}</pre>
        </details>
      )}
      {step.error_message && <p role="alert" className="mt-3 text-xs text-[var(--danger)]">{step.error_message}</p>}
      {step.result_json && (
        <details className="mt-2 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)]">
          <summary className="cursor-pointer px-3 py-2 text-xs font-medium">Result</summary>
          <pre className="overflow-x-auto border-t border-[var(--border)] px-3 py-2 font-mono text-[11px] leading-5 text-[var(--muted)]">{JSON.stringify(step.result_json, null, 2)}</pre>
        </details>
      )}
    </article>
  );
}
