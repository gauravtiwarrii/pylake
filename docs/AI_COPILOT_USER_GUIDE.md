# PyLake AI Copilot user guide

## Open Copilot

Use **AI Copilot** in a workspace's sidebar for the full conversation experience, or open the sparkle button in the application header for the compact panel. The panel and full page share the same workspace-scoped conversation APIs. Copilot is available only when an administrator has configured a provider on the server.

The full page lists your recent conversations. Start a new conversation, select one of your previous conversations, or delete a conversation. Messages are streamed as the response arrives.

## Contextual actions

- From Data Explorer, select a dataset and choose **Ask Copilot about this dataset**. Use **Analyze dataset** to request its actual bounded profile and an explanation of the returned metrics.
- From SQL Workspace, choose **Ask Copilot** to include the current SQL text as context. Use the Copilot prompt to ask for an explanation or debugging help.
- From Pipelines, choose **Ask Copilot** for a workspace-scoped view of the selected pipeline's metadata.

Context is limited to authorized workspace metadata. Raw dataset rows are not included in chat context.

## Generate reviewable drafts

Write a request, then choose one of the draft actions:

- **Generate SQL draft** returns a read-only SQL suggestion validated against queryable tables in the current workspace. Use **Open in SQL Workspace** to review it; it is not run automatically.
- **Generate transform draft** is available when a dataset or table is in context. The suggested operation and columns are checked against the selected asset's schema.
- **Generate pipeline draft** returns a validated pipeline graph with `DRAFT` status. It is not created or executed automatically.

Review generated details carefully and use the existing SQL, lakehouse, and pipeline workflows to apply changes. Copilot never claims to have executed a query, transformation, or pipeline.

## Availability and usage

The page displays provider/model availability and recent request usage. Provider-reported token totals may be unavailable for some streaming providers. If Copilot is unavailable, contact the PyLake administrator to check server-side provider configuration and request limits.
