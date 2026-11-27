export type AskCitation = {
  type: string;
  id: string;
  name: string;
  column?: string;
};

export type AskAnswer = {
  answer_type: "metadata" | "data" | "clarification" | "unsupported";
  question: string;
  summary: string;
  sql?: string | null;
  columns?: { name: string; type?: string }[];
  rows?: Record<string, unknown>[];
  table_rows?: Record<string, unknown>[];
  candidate_tables?: { id: string; name: string }[];
  candidate_columns?: { name: string; table?: string; asset_id?: string; type?: string }[];
  row_count: number;
  truncated: boolean;
  chart_suggestion?: { type: "bar" | "line" | "table" | "kpi"; x: string; y: string } | null;
  citations: AskCitation[];
  limitations: string[];
  confidence: "high" | "medium" | "low";
  ai_used: boolean;
  ai_explanation?: string | null;
};

export type AskHistoryItem = {
  id: string;
  question: string;
  answer_type: string;
  sql: string | null;
  citations: AskCitation[];
  created_at: string;
};
