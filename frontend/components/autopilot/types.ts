export type RiskLevel = "LOW" | "MEDIUM" | "HIGH";

export type PlanStep = {
  id: string;
  step_order: number;
  action_key: string;
  title: string;
  rationale: string | null;
  arguments_json: Record<string, unknown>;
  evidence_json: { source?: string; detail?: string }[] | null;
  preview_json: Record<string, unknown> | null;
  risk_level: RiskLevel;
  requires_approval: boolean;
  status: string;
  result_json: Record<string, unknown> | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
};

export type AutopilotPlan = {
  id: string;
  workspace_id: string;
  created_by: string | null;
  goal: string;
  status: "DRAFT" | "PREVIEWED" | "APPROVED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
  plan_hash: string | null;
  ai_provider: string | null;
  ai_model: string | null;
  approved_by: string | null;
  approved_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  report_json: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  steps: PlanStep[];
};

export type Recommendation = {
  id: string;
  page_type: string;
  category: string;
  title: string;
  description: string;
  evidence: { source: string; detail: string }[];
  confidence: RiskLevel;
  expected_impact: string;
  proposed_action: { tool: string; arguments: Record<string, unknown> };
  risk_level: RiskLevel;
  required_permissions: string[];
  approval_required: boolean;
  status: "PROPOSED" | "ACCEPTED" | "REJECTED" | "DISMISSED";
  created_at: string;
};
