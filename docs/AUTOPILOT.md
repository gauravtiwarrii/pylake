# PyLake Autopilot

Autopilot composes a small set of existing PyLake operations into a workspace-scoped plan. Open it from **Autopilot** in the workspace navigation. A plan can be generated from a goal when an AI provider is configured, or assembled manually from the same action allowlist.

## Plan lifecycle

1. Create a plan with a goal and optional dataset context. AI planning returns structured JSON; the server validates each action and its arguments against the allowlist and the selected workspace before saving it. Manual plans use the same validation.
2. Preview a `DRAFT` plan. Each action's preview validates its inputs and describes its expected effects without executing the action. The server records the preview and computes a SHA-256 `plan_hash` over the ordered action keys and canonical JSON arguments.
3. An `EDITOR`, `ADMIN`, or `OWNER` reviews and approves the `PREVIEWED` plan by submitting that hash. The server checks it against both the stored preview hash and the current plan contents.
4. Execute the `APPROVED` plan explicitly. Actions run synchronously, in order. A successful plan becomes `SUCCEEDED` and includes a report of created resources and step durations.

Changing step arguments after approval causes the execution hash check to fail before the changed step runs. The plan is recorded as `FAILED`; later steps are marked `SKIPPED`. An action failure also stops later steps. A user can cancel a `DRAFT`, `PREVIEWED`, `APPROVED`, or `RUNNING` plan; pending steps are marked cancelled. Cancellation is a state transition, not a background job interrupt, so it cannot reliably stop an action already executing.

## Action allowlist and permissions

All action arguments are validated by the backend. Resource IDs must belong to the requested workspace.

| Action | Minimum execution role | Risk | Approval required |
| --- | --- | --- | --- |
| `profile_dataset` | Viewer | Low | No |
| `promote_table` | Editor | Medium | Yes |
| `apply_transformation` | Editor | Medium | Yes |
| `run_readonly_sql` | Viewer | Low | No |
| `create_pipeline` | Editor | Medium | Yes |
| `create_schedule` | Editor | Medium | Yes |

Plan approval and execution require at least Editor access, including for plans that contain only lower-risk actions. A viewer may inspect plans and previews but cannot approve or execute them. Workspace membership is checked on every plan and recommendation route.

## Recommendations

The Autopilot page can show contextual recommendations for a selected dataset. Each recommendation includes its evidence, confidence, risk, and suggested tool. **Dismiss** records a decision. **Accept and create plan** creates a one-step `DRAFT` plan; it does not approve or execute the action. Review and preview that plan through the normal lifecycle.

## AI-disabled mode

AI is optional. If the workspace AI status endpoint reports that no provider is configured, the page explains that generated planning is unavailable and opens the manual step builder. Manual plans still receive server-side allowlist, schema, role, and workspace validation.

## Security and limitations

- The server owns action validation, workspace scoping, permission checks, preview generation, hash verification, and execution. Browser-side JSON validation is only an editing aid.
- The approval hash binds the ordered action keys and arguments. It does not attest to step titles, rationale, or evidence.
- Previews are designed to perform no writes. They validate arguments and report expected behavior; they do not guarantee that execution will succeed against data that changes afterward.
- Plans are executed synchronously by the API request. Long actions occupy the request until they complete, and there is no durable worker, retry queue, or reliable interruption mechanism for an action already in progress.
- Each plan stops after its first failed action. Completed earlier actions are not automatically rolled back; inspect the report and any created resources before retrying.
- AI prompts and bounded workspace context are sent to the configured provider when AI planning is used. Avoid putting secrets or credentials in goals. Review the [AI Copilot security guide](AI_COPILOT_SECURITY.md) before enabling an external provider.

## API routes

- `POST /api/v1/workspaces/{workspace_id}/ai/autopilot/plans`
- `GET /api/v1/workspaces/{workspace_id}/ai/autopilot/plans`
- `GET /api/v1/workspaces/{workspace_id}/ai/autopilot/plans/{plan_id}`
- `POST /api/v1/workspaces/{workspace_id}/ai/autopilot/plans/{plan_id}/preview`
- `POST /api/v1/workspaces/{workspace_id}/ai/autopilot/plans/{plan_id}/approve`
- `POST /api/v1/workspaces/{workspace_id}/ai/autopilot/plans/{plan_id}/execute`
- `POST /api/v1/workspaces/{workspace_id}/ai/autopilot/plans/{plan_id}/cancel`
- `GET /api/v1/workspaces/{workspace_id}/ai/autopilot/plans/{plan_id}/report`
- `GET /api/v1/workspaces/{workspace_id}/ai/recommendations`
- `POST /api/v1/workspaces/{workspace_id}/ai/recommendations`
- `POST /api/v1/workspaces/{workspace_id}/ai/recommendations/{recommendation_id}/dismiss`
- `POST /api/v1/workspaces/{workspace_id}/ai/recommendations/{recommendation_id}/accept`
