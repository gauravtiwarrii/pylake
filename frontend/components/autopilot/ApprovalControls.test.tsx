import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApproveButton } from "./ApprovalControls";
import type { AutopilotPlan } from "./types";

const plan = (status: AutopilotPlan["status"]): AutopilotPlan => ({
  id: "plan-1",
  workspace_id: "workspace-1",
  created_by: "user-1",
  goal: "Prepare data",
  status,
  plan_hash: "a".repeat(64),
  ai_provider: null,
  ai_model: null,
  approved_by: null,
  approved_at: null,
  started_at: null,
  completed_at: null,
  error_message: null,
  report_json: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  steps: [],
});

describe("ApproveButton", () => {
  it("is disabled until a plan is PREVIEWED", () => {
    const onApprove = vi.fn();
    const { rerender } = render(<ApproveButton plan={plan("DRAFT")} busy={false} onApprove={onApprove} />);
    expect(screen.getByRole("button", { name: "Approve plan" })).toBeDisabled();
    rerender(<ApproveButton plan={plan("PREVIEWED")} busy={false} onApprove={onApprove} />);
    expect(screen.getByRole("button", { name: "Approve plan" })).toBeEnabled();
  });
});
