export type MetricStatus = "MEASURED" | "NOT_MEASURED";
export type TrustMetric = {
  score: number | null;
  status: MetricStatus;
  value: unknown;
  detail: string;
  basis: string;
};

export type TrustRule = {
  id: string;
  column_name: string | null;
  rule_type: "NOT_NULL" | "UNIQUE" | "RANGE" | "REGEX" | "ALLOWED_VALUES" | "MIN_ROW_COUNT";
  config_json: Record<string, unknown>;
  severity: "LOW" | "MEDIUM" | "HIGH";
  enabled: boolean;
};

export type TrustSnapshot = {
  id: string;
  asset_id: string;
  overall_score: number | null;
  metrics: Record<string, TrustMetric>;
  measured_metrics: string[];
  excluded_metrics: string[];
  rule_results: { rule_id: string; rule_type: string; column_name: string | null; severity: string; status: string; passed: number; checked: number; basis: string }[];
  limitations: string[];
  sample_rows: number;
  total_rows: number | null;
  sampled: boolean;
  trigger: string;
  computed_at: string;
  last_successful_validation: string | null;
};
