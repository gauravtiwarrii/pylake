import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RiskBadge } from "./RiskBadge";

describe("RiskBadge", () => {
  it("renders the risk level accessibly", () => {
    render(<RiskBadge risk="HIGH" />);
    expect(screen.getByText("HIGH risk")).toBeInTheDocument();
  });
});
