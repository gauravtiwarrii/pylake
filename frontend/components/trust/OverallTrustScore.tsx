export function OverallTrustScore({ score }: { score: number | null }) {
  const measured = score !== null;
  const stroke = measured ? Math.max(0, Math.min(100, score)) : 0;
  return (
    <div role="img" aria-label={measured ? `Overall trust score ${score.toFixed(1)} out of 100` : "Overall trust score not measured"} className="relative grid size-28 shrink-0 place-items-center">
      <svg aria-hidden="true" viewBox="0 0 100 100" className="absolute inset-0 -rotate-90">
        <circle cx="50" cy="50" r="43" fill="none" stroke="var(--border)" strokeWidth="8" />
        {measured && <circle cx="50" cy="50" r="43" fill="none" stroke="var(--accent)" strokeWidth="8" strokeDasharray={`${stroke * 2.702} 270.2`} strokeLinecap="round" />}
      </svg>
      <span className="text-center"><strong className="block text-2xl tabular-nums">{measured ? score.toFixed(0) : "—"}</strong><span className="text-[10px] text-[var(--muted)]">{measured ? "of 100" : "not measured"}</span></span>
    </div>
  );
}
