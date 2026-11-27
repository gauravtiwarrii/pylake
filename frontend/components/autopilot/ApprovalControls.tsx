import type { AutopilotPlan } from "./types";

export function ApproveButton({
  plan,
  busy,
  onApprove,
}: {
  plan: AutopilotPlan;
  busy: boolean;
  onApprove: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onApprove}
      disabled={busy || plan.status !== "PREVIEWED"}
      className="h-10 rounded-lg bg-[var(--accent)] px-4 text-sm font-semibold text-[var(--accent-foreground)] hover:bg-[var(--accent-strong)] disabled:cursor-not-allowed disabled:opacity-45"
    >
      {busy ? "Approving…" : "Approve plan"}
    </button>
  );
}
