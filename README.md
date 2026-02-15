# Contract Review OA - Full Stack V1

Contract Review OA is a lightweight full-stack application for purchase-order and contract review workflows, including approvals, aging reminders, role-based administration, and an in-browser operations console.

## Installation

### 1) Prerequisites
- Python 3.10+
- `pip`
- (Optional) SQL Server ODBC driver if using MS SQL Server (`ODBC Driver 18 for SQL Server`)

### 2) Clone and install dependencies
```bash
git clone <your-repo-url>
cd ContractReviewOA
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3) Run the server
```bash
python3 -m contract_review.server
```

Application URL: `http://localhost:8000`

### 4) Run tests
```bash
pytest
```

---

## Configuration

The application is configured through environment variables.

### Core runtime
- `PORT` (default: `8000`)
- `CONTRACT_REVIEW_STORAGE` (default: `storage`)

### Database configuration

#### SQLite (default)
- `CONTRACT_REVIEW_DB_PROVIDER=sqlite`
- `CONTRACT_REVIEW_DB=contract_review.db`

#### MS SQL Server
- `CONTRACT_REVIEW_DB_PROVIDER=mssql`
- `CONTRACT_REVIEW_MSSQL_CONNECTION="Driver={ODBC Driver 18 for SQL Server};Server=<server>;Database=<db>;Trusted_Connection=yes;TrustServerCertificate=yes;"`

The SQL Server schema is in `contract_review/sql/mssql_schema.sql` and is applied automatically at startup.

### Authentication model

Production target is AD-integrated authentication (for example, IIS/Windows Auth) via server variables:
- `REMOTE_USER` or `LOGON_USER`
- `REMOTE_GROUPS` (comma/semicolon-delimited)

Local development fallback headers are supported and can be disabled:
- `ALLOW_DEV_HEADERS=true|false` (default: `true`)
- `X-Remote-User`
- `X-User-Roles`

### SMTP notifications

Notification events are saved in the database and can also be delivered via SMTP when configured:
- `SMTP_HOST`
- `SMTP_PORT` (default: `25`)
- `SMTP_SENDER`
- `SMTP_USERNAME` / `SMTP_PASSWORD` (optional)
- `SMTP_STARTTLS=true|false`

### Reminder scheduler

A built-in background scheduler can run aging reminders automatically:
- `REMINDER_INTERVAL_SECONDS` (set `> 0` to enable)
- `SYSTEM_USER` (default: `system.scheduler`)

Manual trigger endpoint:
- `POST /api/system/run-reminders`

---

## User documentation

For step-by-step UI usage instructions, see:
- [`docs/USER_DOCUMENTATION.md`](docs/USER_DOCUMENTATION.md)

---

## Feature scope implemented

- Workflow lifecycle: status transitions, hold/release, rejection/resubmission
- Parallel/sequential approval-step metadata and decision processing
- Golden PO single-document enforcement
- Append-only audit logging
- Dashboard summary, pending approvals, aging, correction queue
- Admin settings, roles, user-role mapping
- Aging reminder execution endpoint (`POST /api/system/run-reminders`)
- Frontend for creating workflows and viewing dashboard/workflow details

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
