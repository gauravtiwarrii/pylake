import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AskAnswerCard } from "./AskAnswerCard";
import { AskChart, CitationChips, ClarificationOptions } from "./AskVisuals";
import type { AskAnswer } from "./types";

const answer = (type: "kpi" | "bar" | "line" | "table"): AskAnswer => ({
  answer_type: "data", question: "Show results", summary: "Real query results.",
  columns: [{ name: "month" }, { name: "revenue" }], rows: [{ month: "2026-01", revenue: 12 }],
  row_count: 1, truncated: false, chart_suggestion: { type, x: "month", y: "revenue" },
  citations: [], limitations: [], confidence: "high", ai_used: false,
});

describe("Ask Lakehouse visuals", () => {
  it.each(["kpi", "bar", "line", "table"] as const)("renders the %s chart choice", (type) => {
    render(<AskChart answer={answer(type)} />);
    expect(screen.getByTestId(`ask-chart-${type}`)).toBeInTheDocument();
  });

  it("renders citations as workspace links", () => {
    render(<CitationChips workspaceId="ws-1" citations={[{ type: "table", id: "table-1", name: "sales", column: "revenue" }]} />);
    expect(screen.getByRole("link", { name: "table: sales · revenue" })).toHaveAttribute("href", "/workspaces/ws-1/catalog?search=sales");
  });

  it("renders clarification choices and lets a user refine", () => {
    const onChoose = vi.fn();
    render(<ClarificationOptions tables={[{ id: "asset-1", name: "sales" }]} columns={[{ name: "revenue", table: "sales" }]} onChoose={onChoose} />);
    fireEvent.click(screen.getByRole("button", { name: "sales" }));
    fireEvent.click(screen.getByRole("button", { name: "revenue · sales" }));
    expect(onChoose).toHaveBeenNthCalledWith(1, { kind: "table", name: "sales" });
    expect(onChoose).toHaveBeenNthCalledWith(2, { kind: "column", name: "revenue", table: "sales" });
  });

  it("shows the AI estimate label only when an explanation exists", () => {
    const base = answer("table");
    const { rerender } = render(<AskAnswerCard answer={base} workspaceId="ws-1" onRefine={vi.fn()} />);
    expect(screen.queryByText("AI estimate:")).not.toBeInTheDocument();
    rerender(<AskAnswerCard answer={{ ...base, ai_explanation: "A bounded estimate." }} workspaceId="ws-1" onRefine={vi.fn()} />);
    expect(screen.getByText(/AI estimate:/)).toBeInTheDocument();
  });
});
