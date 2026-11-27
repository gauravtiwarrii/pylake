import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PlanStepCard } from "./PlanStepCard";
import type { PlanStep } from "./types";

const step: PlanStep = {
  id: "step-1",
  step_order: 1,
  action_key: "profile_dataset",
  title: "Profile customer data",
  rationale: "Confirm the data quality baseline.",
  arguments_json: { dataset_id: "dataset-123", sample_limit: 100 },
  evidence_json: [{ source: "dataset_metadata", detail: "Dataset has 24 rows." }],
  preview_json: { writes: false, row_count: 24 },
  risk_level: "LOW",
  requires_approval: false,
  status: "PREVIEWED",
  result_json: null,
  error_message: null,
  started_at: null,
  completed_at: null,
};

describe("PlanStepCard", () => {
  it("shows the action arguments and evidence", () => {
    render(<PlanStepCard step={step} />);
    expect(screen.getByText("Profile customer data")).toBeInTheDocument();
    expect(screen.getByText("dataset_metadata:")).toBeInTheDocument();
    expect(screen.getByText("Dataset has 24 rows.")).toBeInTheDocument();
    expect(screen.getByText(/dataset-123/)).toBeInTheDocument();
    expect(screen.getByText(/sample_limit/)).toBeInTheDocument();
    expect(screen.getByText("Preview")).toBeInTheDocument();
  });
});
