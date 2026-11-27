"use client";

export function TrustBadge({ score }: { score: number | null | undefined }) {
  return <span aria-label={score == null ? "Trust not measured" : `Trust ${score.toFixed(0)} out of 100`} className="inline-flex items-center rounded-full border border-[var(--border)] px-2 py-1 text-xs text-[var(--muted)]">{score == null ? "Not measured" : `Trust ${score.toFixed(0)}`}</span>;
}
