# Orbitly Integrations

Orbitly connects to the tools your team already uses. Integrations are managed from Settings > Integrations.

## Native integrations (no API key required)
- **Slack** - post task updates and deadline reminders to any channel. Available on all plans.
- **Google Calendar** - two-way sync of project deadlines and milestones. Available on all plans.
- **Google Drive / Dropbox** - attach files from cloud storage directly to tasks, without using your Orbitly storage quota. Available on Growth and Scale plans only.
- **Zapier** - Orbitly has an official Zapier app with triggers (new task, task completed, project created) and actions (create task, update task status). Available on all plans.

## API access
Full REST API access (create/read/update/delete on projects, tasks, time entries, and users) is available on the Scale plan only. API keys are generated from Settings > API Access and are scoped per-user with read-only or read-write permissions. Rate limit is 600 requests per minute per key.

## Webhooks
Available on Growth and Scale plans. Webhooks can be configured to fire on: task created, task status changed, project created, project archived, time entry logged. Webhook payloads are signed with HMAC-SHA256 using a per-webhook secret shown once at creation time.

## Make.com and n8n
Orbitly does not have an official Make.com or n8n connector at this time. Both tools can be connected using Orbitly's generic REST API (Scale plan required) via their respective HTTP/webhook modules.

## Single Sign-On (SSO)
SAML-based SSO (Okta, Azure AD, Google Workspace) is available on the Scale plan only. SCIM user provisioning is supported for automatic user creation/deactivation when configured through your identity provider.
