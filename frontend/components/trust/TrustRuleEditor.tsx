"use client";

import { useState } from "react";
import type { TrustRule } from "./types";

export function validateRuleConfig(ruleType: string, text: string): string | null {
  let value: unknown;
  try { value = JSON.parse(text); } catch { return "Enter valid JSON."; }
  if (!value || typeof value !== "object" || Array.isArray(value)) return "Configuration must be a JSON object.";
  const config = value as Record<string, unknown>;
  if (ruleType === "RANGE" && (typeof config.min !== "number" || typeof config.max !== "number" || config.min > config.max)) return "Range needs numeric min and max, with min no greater than max.";
  if (ruleType === "REGEX") {
    if (typeof config.pattern !== "string" || config.pattern.length > 500) return "Regex pattern is required and limited to 500 characters.";
    try { new RegExp(config.pattern); } catch { return "Regex pattern is invalid."; }
  }
  if (ruleType === "ALLOWED_VALUES" && (!Array.isArray(config.values) || config.values.length === 0 || config.values.length > 500)) return "Provide between 1 and 500 allowed values.";
  if (ruleType === "MIN_ROW_COUNT" && (!Number.isInteger(config.min) || Number(config.min) < 0)) return "Minimum row count must be a non-negative integer.";
  return null;
}

const RULE_TYPES = ["NOT_NULL", "UNIQUE", "RANGE", "REGEX", "ALLOWED_VALUES", "MIN_ROW_COUNT"];
export function TrustRuleEditor({ rules, canEdit, onSave, onToggle, onDelete, freshness, onFreshness }: {
  rules: TrustRule[]; canEdit: boolean; onSave: (rule: { column_name: string | null; rule_type: string; config_json: Record<string, unknown>; severity: string; enabled: boolean }, id?: string) => Promise<void>;
  onToggle: (rule: TrustRule) => Promise<void>; onDelete: (rule: TrustRule) => Promise<void>; freshness: number | null; onFreshness: (hours: number) => Promise<void>;
}) {
  const [type, setType] = useState(RULE_TYPES[0]); const [column, setColumn] = useState(""); const [json, setJson] = useState("{}"); const [severity, setSeverity] = useState("MEDIUM"); const [error, setError] = useState(""); const [editingId, setEditingId] = useState<string | undefined>();
  async function submit(event: React.FormEvent) {
    event.preventDefault(); const problem = validateRuleConfig(type, json); if (problem) { setError(problem); return; }
    setError(""); await onSave({ column_name: column.trim() || null, rule_type: type, config_json: JSON.parse(json), severity, enabled: true }, editingId); setEditingId(undefined);
  }
  return <section className="space-y-4 rounded-xl border border-[var(--border)] p-4" aria-label="Quality rules">
    <h3 className="font-semibold">Quality rules</h3>
    {rules.length ? <ul className="space-y-2">{rules.map(rule => <li key={rule.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-[var(--surface-raised)] p-3 text-sm"><span>{rule.rule_type}{rule.column_name ? ` · ${rule.column_name}` : ""} · {rule.severity}</span><span className="flex gap-2"><button type="button" disabled={!canEdit} onClick={() => { setEditingId(rule.id); setType(rule.rule_type); setColumn(rule.column_name ?? ""); setJson(JSON.stringify(rule.config_json, null, 2)); setSeverity(rule.severity); }} className="underline">Edit</button><button type="button" disabled={!canEdit} onClick={() => void onToggle(rule)} className="underline">{rule.enabled ? "Disable" : "Enable"}</button><button type="button" disabled={!canEdit} onClick={() => void onDelete(rule)} className="underline">Delete</button></span></li>)}</ul> : <p className="text-sm text-[var(--muted)]">No quality rules yet.</p>}
    {canEdit && <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
      <label className="text-sm">Rule type<select aria-label="Rule type" value={type} onChange={e => setType(e.target.value)} className="mt-1 block h-10 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-2">{RULE_TYPES.map(t => <option key={t}>{t}</option>)}</select></label>
      <label className="text-sm">Column (optional)<input aria-label="Rule column" value={column} onChange={e => setColumn(e.target.value)} className="mt-1 block h-10 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-2" /></label>
      <label className="text-sm md:col-span-2">Configuration JSON<textarea aria-label="Rule configuration JSON" value={json} onChange={e => setJson(e.target.value)} rows={3} className="mt-1 block w-full rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-2 font-mono text-xs" /></label>
      <label className="text-sm">Severity<select aria-label="Rule severity" value={severity} onChange={e => setSeverity(e.target.value)} className="mt-1 block h-10 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-2"><option>LOW</option><option>MEDIUM</option><option>HIGH</option></select></label>
      {error && <p role="alert" className="text-sm text-red-400 md:col-span-2">{error}</p>}<button className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-black">{editingId ? "Save rule" : "Add rule"}</button>{editingId && <button type="button" onClick={() => setEditingId(undefined)} className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm">Cancel edit</button>}
    </form>}
    {canEdit && <form className="flex flex-wrap items-end gap-3" onSubmit={e => { e.preventDefault(); const hours = Number(new FormData(e.currentTarget).get("freshness")); if (hours >= 1 && hours <= 8760) void onFreshness(hours); }}><label className="text-sm">Freshness target (hours)<input name="freshness" type="number" min="1" max="8760" defaultValue={freshness ?? ""} className="mt-1 block h-10 w-44 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-2" /></label><button className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm">Save target</button></form>}
  </section>;
}
