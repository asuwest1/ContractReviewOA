# CLAUDE.md

## Project Overview

Contract Review OA is a full-stack application for purchase-order and contract review workflows. It handles approvals, aging reminders, role-based administration, and provides an in-browser operations console. The backend is Python using the stdlib `http.server` (no framework); the frontend is vanilla HTML/JS/CSS.

## Tech Stack

- **Backend**: Python 3.10+ with `http.server.ThreadingHTTPServer` (no web framework)
- **Frontend**: Vanilla HTML, JavaScript, CSS (served from `web/`)
- **Database**: SQLite (default) or MS SQL Server via ODBC
- **Testing**: pytest
- **Email**: smtplib (optional SMTP notifications)

## Project Structure

```
contract_review/          # Python package (backend)
  __init__.py
  server.py               # HTTP server, routing, request handling
  service.py              # Core business logic (AppService), DB client, RBAC
  auth.py                 # Authentication resolver (AD/dev-header fallback)
  mailer.py               # SMTP email notifications
  scheduler.py            # Background aging-reminder scheduler
  sql/
    mssql_schema.sql      # SQL Server schema (auto-applied at startup)
web/                      # Frontend (static files)
  index.html
  app.js
  styles.css
tests/                    # Test suite
  test_service.py         # Service layer tests
  test_auth_mailer_mssql.py  # Auth, mailer, and MSSQL tests
docs/
  USER_DOCUMENTATION.md   # End-user UI guide
pyproject.toml            # pytest configuration
```

## Setup and Commands

### Install
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Run the server
```bash
python3 -m contract_review.server
```
Listens on `http://localhost:8000` by default (configurable via `PORT` env var).

### Run tests
```bash
pytest
```
pytest is configured in `pyproject.toml` with `pythonpath = ["."]` and `addopts = "-q"`.

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8000` | Server listen port |
| `CONTRACT_REVIEW_STORAGE` | `storage` | File storage root directory |
| `CONTRACT_REVIEW_DB_PROVIDER` | `sqlite` | Database provider (`sqlite` or `mssql`) |
| `CONTRACT_REVIEW_DB` | `contract_review.db` | SQLite database path |
| `CONTRACT_REVIEW_MSSQL_CONNECTION` | _(empty)_ | MSSQL ODBC connection string |
| `CONTRACT_REVIEW_UNC_BASE` | `\\FQDN\Subfolder` | UNC path base for document storage |
| `ALLOW_DEV_HEADERS` | `false` | Enable dev auth headers (`X-Remote-User`, `X-User-Roles`) |
| `DEFAULT_ROLES` | _(empty)_ | Comma-separated default roles for all users |
| `SMTP_HOST` | _(empty)_ | SMTP server (enables email when set) |
| `SMTP_PORT` | `25` | SMTP port |
| `SMTP_SENDER` | `noreply@contractreview.local` | Email from address |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | _(empty)_ | SMTP credentials (optional) |
| `SMTP_STARTTLS` | `false` | Enable STARTTLS for SMTP |
| `REMINDER_INTERVAL_SECONDS` | `0` | Aging reminder interval (>0 to enable scheduler) |
| `SYSTEM_USER` | `system.scheduler` | User identity for scheduled reminders |

## Architecture Notes

- **No web framework**: The server uses Python's stdlib `http.server.ThreadingHTTPServer` with manual routing in `ApiHandler`.
- **Single-file business logic**: Nearly all domain logic lives in `service.py` (`AppService` class), including the embedded `DbClient` that abstracts SQLite vs MSSQL.
- **SQLite schema**: Created inline in `AppService._init_db()` using `CREATE TABLE IF NOT EXISTS`.
- **MSSQL schema**: Applied from `contract_review/sql/mssql_schema.sql` at startup.
- **Authentication**: Production uses AD/Windows Auth via server variables (`REMOTE_USER`, `LOGON_USER`). Dev mode uses `X-Remote-User` / `X-User-Roles` headers when `ALLOW_DEV_HEADERS=true`.
- **RBAC**: Role-based permissions are defined in `ROLE_PERMISSIONS` dict in `service.py`. Roles include Admin, Customer Service, Technical, Commercial, etc.
- **CSRF protection**: Origin header validation on state-changing requests.

## Coding Conventions

- Python 3.10+ type hints (using `str | None` union syntax, not `Optional`)
- `dataclass` for simple data objects (`Identity`, `RequestContext`)
- Constants defined at module level in UPPER_SNAKE_CASE
- Exceptions used for control flow: `KeyError` -> 404, `PermissionError` -> 403, `ValueError` -> 400
- Test functions use `tmp_path` fixture for isolated SQLite databases
- `# noqa` comments used for specific suppressions (`N802` for HTTP method names, `BLE001` for broad except)

## Key Domain Concepts

- **Workflow**: Central entity with a lifecycle (Active -> Reviewing -> Negotiating -> Archived/Rejected/Cancelled)
- **Approval Steps**: Parallel or sequential approval steps with assigned roles and users
- **Golden PO**: Single-document enforcement rule for purchase orders
- **Aging Reminders**: Automatic notifications for workflows exceeding configurable age thresholds
- **Hold/Release**: Workflows can be placed on hold and released
- **Correction Queue**: Rejected workflows appear here for resubmission
