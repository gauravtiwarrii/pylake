import { RiskBadge } from "./RiskBadge";
import type { Recommendation } from "./types";

export function ProposedActionCard({
  recommendation,
  busy = false,
  onAccept,
  onDismiss,
}: {
  recommendation: Recommendation;
  busy?: boolean;
  onAccept: () => void;
  onDismiss: () => void;
}) {
  return (
    <article className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h3 className="font-medium">{recommendation.title}</h3>
        <RiskBadge risk={recommendation.risk_level} />
      </div>
      <p className="mt-2 text-sm leading-6 text-[var(--muted)]">{recommendation.description}</p>
      {recommendation.evidence.length > 0 && (
        <ul className="mt-3 space-y-1">
          {recommendation.evidence.map((item, index) => (
            <li key={`${item.source}-${index}`} className="text-xs leading-5 text-[var(--muted)]">
              <span className="font-medium text-[var(--foreground)]">{item.source}: </span>{item.detail}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-[var(--muted)]">
        Confidence: {recommendation.confidence} · Suggested action: <code>{recommendation.proposed_action.tool}</code>
      </p>
      <p className="mt-1 text-xs text-[var(--muted)]">{recommendation.expected_impact}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" onClick={onAccept} disabled={busy} className="h-9 rounded-lg bg-[var(--accent)] px-3 text-xs font-semibold text-[var(--accent-foreground)] hover:bg-[var(--accent-strong)] disabled:cursor-not-allowed disabled:opacity-50">
          {busy ? "Working…" : "Accept and create plan"}
        </button>
        <button type="button" onClick={onDismiss} disabled={busy} className="h-9 rounded-lg border border-[var(--border-strong)] px-3 text-xs font-medium hover:bg-[var(--surface-hover)] disabled:cursor-not-allowed disabled:opacity-50">
          Dismiss
        </button>
      </div>
    </article>
  );
}
