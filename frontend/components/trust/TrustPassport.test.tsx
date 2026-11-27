import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { OverallTrustScore } from "./OverallTrustScore";
import { TrustMetricCard } from "./TrustMetricCard";
import { TrustRuleEditor, validateRuleConfig } from "./TrustRuleEditor";

describe("Trust Passport components", () => {
  it("does not show a score for a NOT MEASURED metric", () => {
    render(<TrustMetricCard name="freshness" metric={{ status: "NOT_MEASURED", score: null, value: null, detail: "No target configured", basis: "Freshness target required" }} />);
    expect(screen.getByText("NOT MEASURED")).toBeInTheDocument();
    expect(screen.getByText("Score not shown")).toBeInTheDocument();
    expect(screen.queryByText("100.0")).not.toBeInTheDocument();
  });

  it("renders the overall score with an accessible label", () => {
    render(<OverallTrustScore score={82.5} />);
    expect(screen.getByRole("img", { name: "Overall trust score 82.5 out of 100" })).toBeInTheDocument();
    expect(screen.getByText("83")).toBeInTheDocument();
  });

  it("validates rule configuration before submission", async () => {
    expect(validateRuleConfig("RANGE", "{\"min\":5,\"max\":2}")).toMatch(/Range needs/);
    expect(validateRuleConfig("REGEX", "{\"pattern\":\"[\"}")).toBe("Regex pattern is invalid.");
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<TrustRuleEditor rules={[]} canEdit onSave={onSave} onToggle={vi.fn()} onDelete={vi.fn()} freshness={null} onFreshness={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Add rule" })).toBeEnabled();
  });
});
