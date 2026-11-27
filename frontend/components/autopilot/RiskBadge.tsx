import type { RiskLevel } from "./types";

const styles: Record<RiskLevel, string> = {
  LOW: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  MEDIUM: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  HIGH: "border-rose-500/30 bg-rose-500/10 text-rose-300",
};

export function RiskBadge({ risk }: { risk: RiskLevel }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${styles[risk]}`}>
      {risk} risk
    </span>
  );
}
