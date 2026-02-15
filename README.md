# Contract Review OA - Full Stack V1

This repository includes a runnable full-stack V1 implementation (frontend + backend) for PO/Contract review workflows.

## Run

```bash
python3 -m contract_review.server
```

Open: `http://localhost:8000`

## Database configuration

### SQLite (default)
- `CONTRACT_REVIEW_DB_PROVIDER=sqlite`
- `CONTRACT_REVIEW_DB=contract_review.db`

### MS SQL Server
- `CONTRACT_REVIEW_DB_PROVIDER=mssql`
- `CONTRACT_REVIEW_MSSQL_CONNECTION="Driver={ODBC Driver 18 for SQL Server};Server=<server>;Database=<db>;Trusted_Connection=yes;TrustServerCertificate=yes;"`

MS SQL schema is included at `contract_review/sql/mssql_schema.sql` and applied automatically at startup.

## Authentication model (task #1)

- Production target is AD Integrated Auth (IIS/Windows auth) via `REMOTE_USER` / `LOGON_USER` server variables.
- Role/group hydration can be provided through `REMOTE_GROUPS` (comma/semicolon delimited).
- Local fallback headers are available for development and can be disabled:
  - `ALLOW_DEV_HEADERS=true|false` (default `true`)
  - `X-Remote-User`
  - `X-User-Roles`

## SMTP notifications (task #2)

Notification events are recorded in DB and can be sent via SMTP when configured:

- `SMTP_HOST`
- `SMTP_PORT` (default `25`)
- `SMTP_SENDER`
- `SMTP_USERNAME` / `SMTP_PASSWORD` (optional)
- `SMTP_STARTTLS=true|false`

## Reminder scheduler (task #3)

A built-in background scheduler can trigger aging reminders automatically:

- `REMINDER_INTERVAL_SECONDS` (set `> 0` to enable)
- `SYSTEM_USER` (default `system.scheduler`)

Manual trigger endpoint is also available: `POST /api/system/run-reminders`.

## Functional scope implemented

- Workflow lifecycle (all required statuses, hold/release, rejection/resubmission)
- Parallel/sequential approval-step metadata and decision processing
- Golden PO single-document enforcement
- Append-only audit logging
- Dashboard summary + pending approvals + aging + correction queue
- Admin settings, roles, and user-role mapping
- Aging reminder execution endpoint (`POST /api/system/run-reminders`)
- Frontend UI for creating workflows and viewing dashboard/workflow details

## Core API endpoints

- `POST /api/workflows`
- `GET /api/workflows`
- `GET /api/workflows/{id}`
- `PUT /api/workflows/{id}/status`
- `PUT /api/workflows/{id}/hold`
- `POST /api/workflows/{id}/documents`
- `POST /api/approvals/{stepId}/decide`
- `GET /api/dashboard/summary`
- `GET /api/dashboard/pending`
- `GET /api/dashboard/aging`
- `GET /api/dashboard/correction-queue`
- `POST /api/system/run-reminders`
- `GET /api/notifications`
- `GET/PUT /api/admin/settings`
- `GET/POST /api/admin/roles`
- `GET/PUT /api/admin/user-roles`
