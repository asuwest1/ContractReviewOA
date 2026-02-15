import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contract_review.mailer import SmtpMailer

logger = logging.getLogger(__name__)

ISO = "%Y-%m-%dT%H:%M:%SZ"
ALLOWED_STATUSES = {
    "Active",
    "Reviewing",
    "Negotiating",
    "Archived",
    "In Review",
    "Rejected",
    "Cancelled",
}
IN_PROCESS_STATUSES = {"Active", "Reviewing", "Negotiating", "In Review"}
ALLOWED_DOC_TYPES = {"PO", "Contract"}
ALLOWED_SETTING_KEYS = {f"aging_threshold_{i}" for i in range(1, 6)}
MAX_TITLE_LENGTH = 255
MAX_COMMENT_LENGTH = 2000
MAX_REASON_LENGTH = 1000
MAX_ROLE_NAME_LENGTH = 100

# --- RBAC Permission Constants ---
PERM_WORKFLOW_CREATE = "workflow:create"
PERM_WORKFLOW_VIEW_ALL = "workflow:view_all"
PERM_WORKFLOW_MANAGE_ALL = "workflow:manage_all"
PERM_DASHBOARD_FULL = "dashboard:full"
PERM_ADMIN_SETTINGS = "admin:settings"
PERM_ADMIN_ROLES = "admin:roles"
PERM_SYSTEM_REMINDERS = "system:reminders"

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "Admin": {
        PERM_WORKFLOW_CREATE,
        PERM_WORKFLOW_VIEW_ALL,
        PERM_WORKFLOW_MANAGE_ALL,
        PERM_DASHBOARD_FULL,
        PERM_ADMIN_SETTINGS,
        PERM_ADMIN_ROLES,
        PERM_SYSTEM_REMINDERS,
    },
    "Customer Service": {
        PERM_WORKFLOW_CREATE,
    },
}


@dataclass
class RequestContext:
    user: str
    roles: set[str]


class DatabaseError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime(ISO)


def _sqlite_row_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


class DbClient:
    """Small DB-API wrapper supporting sqlite and mssql(pyodbc)."""

    def __init__(self, provider: str, connection_string: str):
        self.provider = provider.lower()
        self.connection_string = connection_string
        self.conn = self._connect()

    def _connect(self):
        if self.provider == "sqlite":
            conn = sqlite3.connect(self.connection_string, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn
        if self.provider == "mssql":
            try:
                import pyodbc  # type: ignore
                if not hasattr(pyodbc, "connect"):
                    raise DatabaseError("MSSQL provider requires pyodbc.connect")
                conn = pyodbc.connect(self.connection_string)
            except Exception as exc:  # noqa: BLE001
                raise DatabaseError("MSSQL provider requires pyodbc to be installed and configured") from exc
            conn.autocommit = False
            return conn
        raise DatabaseError(f"Unsupported provider: {self.provider}")

    def _normalize_sql(self, sql: str) -> str:
        if self.provider == "mssql":
            return sql.replace("?", "?")
        return sql

    def execute(self, sql: str, params: tuple[Any, ...] = ()):
        cur = self.conn.cursor()
        cur.execute(self._normalize_sql(sql), params)
        return cur

    def executescript(self, script: str) -> None:
        if self.provider == "sqlite":
            self.conn.executescript(script)
            return
        # split batch by ';' for MSSQL compatibility
        cur = self.conn.cursor()
        for stmt in [s.strip() for s in script.split(";") if s.strip()]:
            cur.execute(stmt)

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def fetchone_dict(self, cur):
        row = cur.fetchone()
        if row is None:
            return None
        if self.provider == "sqlite":
            return dict(row)
        columns = [c[0] for c in cur.description]
        return dict(zip(columns, row))

    def fetchall_dict(self, cur):
        rows = cur.fetchall()
        if self.provider == "sqlite":
            return _sqlite_row_dicts(rows)
        columns = [c[0] for c in cur.description]
        return [dict(zip(columns, r)) for r in rows]


class AppService:
    def __init__(
        self,
        db_provider: str | None = None,
        connection_string: str | None = None,
        storage_root: str = "storage",
    ):
        provider = (db_provider or os.environ.get("CONTRACT_REVIEW_DB_PROVIDER") or "sqlite").lower()
        if connection_string is None:
            if provider == "sqlite":
                connection_string = os.environ.get("CONTRACT_REVIEW_DB", "contract_review.db")
            else:
                connection_string = os.environ.get("CONTRACT_REVIEW_MSSQL_CONNECTION", "")
        self.db = DbClient(provider, connection_string)
        self.storage_root = Path(storage_root)
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.unc_base = os.environ.get("CONTRACT_REVIEW_UNC_BASE", r"\\FQDN\Subfolder")
        self.mailer = SmtpMailer()
        self._init_db()

    def _begin(self):
        return self.db

    def _init_db(self) -> None:
        sqlite_schema = """
        CREATE TABLE IF NOT EXISTS workflows (
            workflow_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            doc_type TEXT NOT NULL,
            current_status TEXT NOT NULL,
            is_hold INTEGER NOT NULL DEFAULT 0,
            resubmitted INTEGER NOT NULL DEFAULT 0,
            created_date TEXT NOT NULL,
            updated_date TEXT NOT NULL,
            created_by TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS workflow_documents (
            doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            is_golden INTEGER NOT NULL DEFAULT 0,
            version INTEGER NOT NULL,
            note TEXT,
            uploaded_by TEXT NOT NULL,
            uploaded_at TEXT NOT NULL,
            FOREIGN KEY(workflow_id) REFERENCES workflows(workflow_id)
        );
        CREATE TABLE IF NOT EXISTS workflow_steps (
            step_id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id INTEGER NOT NULL,
            required_role TEXT NOT NULL,
            sequence_order INTEGER NOT NULL,
            parallel_group INTEGER NOT NULL DEFAULT 0,
            step_status TEXT NOT NULL,
            assigned_to TEXT,
            assigned_date TEXT,
            decision_by TEXT,
            decision_date TEXT,
            decision TEXT,
            decision_comment TEXT,
            FOREIGN KEY(workflow_id) REFERENCES workflows(workflow_id)
        );
        CREATE TABLE IF NOT EXISTS approval_decisions (
            decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id INTEGER NOT NULL,
            step_id INTEGER NOT NULL,
            decision TEXT NOT NULL,
            comment TEXT,
            decided_by TEXT NOT NULL,
            decided_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS status_history (
            history_id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id INTEGER NOT NULL,
            old_status TEXT,
            new_status TEXT NOT NULL,
            changed_by TEXT NOT NULL,
            changed_at TEXT NOT NULL,
            reason TEXT
        );
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS roles (
            role_name TEXT PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS user_roles (
            user_name TEXT NOT NULL,
            role_name TEXT NOT NULL,
            PRIMARY KEY(user_name, role_name)
        );
        CREATE TABLE IF NOT EXISTS notifications (
            notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id INTEGER,
            event TEXT NOT NULL,
            recipient TEXT NOT NULL,
            created_at TEXT NOT NULL,
            payload TEXT
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            action TEXT NOT NULL,
            actor TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reminder_log (
            reminder_id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id INTEGER NOT NULL,
            step_id INTEGER,
            threshold_days INTEGER NOT NULL,
            reminded_at TEXT NOT NULL
        );
        """

        mssql_schema = Path("contract_review/sql/mssql_schema.sql")
        if self.db.provider == "sqlite":
            self.db.executescript(sqlite_schema)
        else:
            self.db.executescript(mssql_schema.read_text())

        defaults = {f"aging_threshold_{i}": str(v) for i, v in enumerate((2, 5, 10, 15, 30), start=1)}
        for key, value in defaults.items():
            self._upsert_setting(key, value)
        for role in ["Customer Service", "Technical", "Commercial", "Legal", "Admin"]:
            self.db.execute("IF NOT EXISTS (SELECT 1 FROM roles WHERE role_name = ?) INSERT INTO roles(role_name) VALUES (?)" if self.db.provider == "mssql" else "INSERT OR IGNORE INTO roles(role_name) VALUES (?)", (role, role) if self.db.provider == "mssql" else (role,))
        self.db.commit()

    def _upsert_setting(self, key: str, value: str) -> None:
        row = self.db.fetchone_dict(self.db.execute("SELECT key FROM system_settings WHERE key = ?", (key,)))
        if row:
            self.db.execute("UPDATE system_settings SET value = ? WHERE key = ?", (value, key))
        else:
            self.db.execute("INSERT INTO system_settings(key, value) VALUES (?, ?)", (key, value))

    def _audit(self, entity_type: str, entity_id: str, action: str, actor: str, details: dict[str, Any] | None = None) -> None:
        self.db.execute(
            "INSERT INTO audit_log(entity_type, entity_id, action, actor, details, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (entity_type, entity_id, action, actor, json.dumps(details or {}), utc_now()),
        )

    def _notify(self, workflow_id: int, event: str, recipients: list[str], payload: dict[str, Any] | None = None) -> None:
        now = utc_now()
        for recipient in recipients:
            self.db.execute(
                "INSERT INTO notifications(workflow_id, event, recipient, created_at, payload) VALUES (?, ?, ?, ?, ?)",
                (workflow_id, event, recipient, now, json.dumps(payload or {})),
            )
            email_sent = False
            email_error = None
            try:
                email_sent = self.mailer.send_event(recipient, event, payload or {})
            except Exception as exc:  # noqa: BLE001
                email_error = str(exc)
            self._audit(
                "notification",
                f"{workflow_id}:{recipient}:{event}",
                "smtp_dispatch",
                "system",
                {"emailSent": email_sent, "error": email_error},
            )

    def _status_folder(self, status: str) -> str:
        if status in {"Archived"}:
            return "Approved"
        if status == "Rejected":
            return "Rejected"
        if status == "Cancelled":
            return "Cancelled"
        return "InProcess"

    def _require_admin(self, ctx: RequestContext) -> None:
        if "Admin" not in ctx.roles:
            raise PermissionError("Admin role required")

    # --- RBAC helpers ---

    def _get_permissions(self, ctx: RequestContext) -> set[str]:
        """Get the union of all permissions for the user's roles."""
        perms: set[str] = set()
        for role in ctx.roles:
            perms.update(ROLE_PERMISSIONS.get(role, set()))
        return perms

    def _has_permission(self, ctx: RequestContext, permission: str) -> bool:
        return permission in self._get_permissions(ctx)

    def _is_workflow_participant(self, workflow_id: int, ctx: RequestContext, workflow: dict[str, Any] | None = None) -> bool:
        """Check if user is a participant in a workflow (creator, assigned to a step, or has matching role for a step)."""
        if workflow is None:
            workflow = self.db.fetchone_dict(self.db.execute(
                "SELECT created_by FROM workflows WHERE workflow_id = ?", (workflow_id,)))
        if not workflow:
            return False
        if workflow.get("created_by") == ctx.user:
            return True
        steps = self.db.fetchall_dict(self.db.execute(
            "SELECT assigned_to, required_role FROM workflow_steps WHERE workflow_id = ?", (workflow_id,)))
        for step in steps:
            if step["assigned_to"] == ctx.user:
                return True
            if step["required_role"] in ctx.roles:
                return True
        return False

    def _require_workflow_access(self, workflow_id: int, ctx: RequestContext, workflow: dict[str, Any] | None = None) -> None:
        """Raise PermissionError if user cannot access the workflow."""
        if self._has_permission(ctx, PERM_WORKFLOW_VIEW_ALL):
            return
        if not self._is_workflow_participant(workflow_id, ctx, workflow):
            raise PermissionError("Access denied to this workflow")

    def _visible_workflow_ids(self, ctx: RequestContext) -> list[int]:
        """Get IDs of all workflows visible to the user."""
        conditions = ["w.created_by = ?", "s.assigned_to = ?"]
        params: list[Any] = [ctx.user, ctx.user]
        if ctx.roles:
            placeholders = ",".join("?" for _ in ctx.roles)
            conditions.append(f"s.required_role IN ({placeholders})")
            params.extend(ctx.roles)
        where = " OR ".join(conditions)
        rows = self.db.fetchall_dict(self.db.execute(
            f"SELECT DISTINCT w.workflow_id FROM workflows w LEFT JOIN workflow_steps s ON s.workflow_id = w.workflow_id WHERE {where}",
            tuple(params)))
        return [r["workflow_id"] for r in rows]

    def create_workflow(self, payload: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
        if not self._has_permission(ctx, PERM_WORKFLOW_CREATE):
            raise PermissionError("Your role does not have permission to create workflows")
        title = str(payload.get("title", "")).strip()
        if not title or len(title) > MAX_TITLE_LENGTH:
            raise ValueError(f"Title is required and must be at most {MAX_TITLE_LENGTH} characters")
        doc_type = payload.get("docType", "PO")
        if doc_type not in ALLOWED_DOC_TYPES:
            raise ValueError(f"docType must be one of: {', '.join(sorted(ALLOWED_DOC_TYPES))}")
        status = payload.get("initialStatus", "Reviewing")
        if status not in ALLOWED_STATUSES:
            raise ValueError("Invalid initial status")
        steps = payload.get("steps", [])
        now = utc_now()
        try:
            cur = self.db.execute(
                "INSERT INTO workflows(title, doc_type, current_status, created_date, updated_date, created_by) VALUES (?, ?, ?, ?, ?, ?)",
                (title, doc_type, status, now, now, ctx.user),
            )
            workflow_id = cur.lastrowid if hasattr(cur, "lastrowid") and cur.lastrowid else self.db.fetchone_dict(self.db.execute("SELECT MAX(workflow_id) AS id FROM workflows"))["id"]
            self.db.execute(
                "INSERT INTO status_history(workflow_id, old_status, new_status, changed_by, changed_at, reason) VALUES (?, ?, ?, ?, ?, ?)",
                (workflow_id, None, status, ctx.user, now, "Workflow created"),
            )
            self._audit("workflow", str(workflow_id), "create", ctx.user, payload)
            for step in steps:
                self.db.execute(
                    """INSERT INTO workflow_steps(workflow_id, required_role, sequence_order, parallel_group, step_status, assigned_to, assigned_date)
                       VALUES (?, ?, ?, ?, 'Pending', ?, ?)""",
                    (workflow_id, step["requiredRole"], int(step.get("sequenceOrder", 1)), int(step.get("parallelGroup", 0)), step.get("assignedTo"), now),
                )
            recipients = [s.get("assignedTo") for s in steps if s.get("assignedTo")]
            if recipients:
                self._notify(workflow_id, "WorkflowLaunched", recipients, {"title": title})
            self._store_document(workflow_id, payload.get("document"), ctx, status)
            self.db.commit()
            return self.get_workflow(workflow_id, ctx)
        except Exception:
            self.db.rollback()
            raise

    def _store_document(self, workflow_id: int, document: dict[str, Any] | None, ctx: RequestContext, current_status: str) -> None:
        if not document:
            return
        is_golden = 1 if document.get("isGolden", False) else 0
        if is_golden:
            existing = self.db.fetchone_dict(self.db.execute("SELECT COUNT(*) AS c FROM workflow_documents WHERE workflow_id = ? AND is_golden = 1", (workflow_id,)))
            if existing and int(existing["c"]) > 0:
                raise ValueError("Only one Golden document is allowed per workflow")
        version = int(document.get("version", 1))
        raw_filename = document.get("filename", f"workflow_{workflow_id}_v{version}.txt")
        if "\x00" in raw_filename:
            raise ValueError("Invalid filename")
        filename = Path(raw_filename).name
        if filename != raw_filename or filename in {"", ".", ".."}:
            raise ValueError("Invalid filename")
        folder = self._status_folder(current_status)
        local_dir = self.storage_root / folder
        local_dir.mkdir(parents=True, exist_ok=True)
        if content := document.get("content"):
            (local_dir / filename).write_text(content, encoding="utf-8")
        unc_path = f"{self.unc_base}\\{folder}\\{filename}"
        self.db.execute(
            "INSERT INTO workflow_documents(workflow_id, file_path, is_golden, version, note, uploaded_by, uploaded_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (workflow_id, unc_path, is_golden, version, document.get("note"), ctx.user, utc_now()),
        )
        self._audit("workflow_document", str(workflow_id), "upload", ctx.user, {"path": unc_path, "isGolden": bool(is_golden)})

    def list_workflows(self, ctx: RequestContext) -> list[dict[str, Any]]:
        if self._has_permission(ctx, PERM_WORKFLOW_VIEW_ALL):
            return self.db.fetchall_dict(self.db.execute("SELECT * FROM workflows ORDER BY workflow_id DESC"))
        conditions = ["w.created_by = ?", "s.assigned_to = ?"]
        params: list[Any] = [ctx.user, ctx.user]
        if ctx.roles:
            placeholders = ",".join("?" for _ in ctx.roles)
            conditions.append(f"s.required_role IN ({placeholders})")
            params.extend(ctx.roles)
        where = " OR ".join(conditions)
        return self.db.fetchall_dict(self.db.execute(
            f"SELECT DISTINCT w.* FROM workflows w LEFT JOIN workflow_steps s ON s.workflow_id = w.workflow_id WHERE {where} ORDER BY w.workflow_id DESC",
            tuple(params)))

    def get_workflow(self, workflow_id: int, ctx: RequestContext) -> dict[str, Any]:
        workflow = self.db.fetchone_dict(self.db.execute("SELECT * FROM workflows WHERE workflow_id = ?", (workflow_id,)))
        if not workflow:
            raise KeyError("Workflow not found")
        self._require_workflow_access(workflow_id, ctx, workflow)
        workflow["documents"] = self.db.fetchall_dict(self.db.execute("SELECT * FROM workflow_documents WHERE workflow_id = ? ORDER BY version", (workflow_id,)))
        workflow["steps"] = self.db.fetchall_dict(self.db.execute("SELECT * FROM workflow_steps WHERE workflow_id = ? ORDER BY sequence_order, step_id", (workflow_id,)))
        workflow["history"] = self.db.fetchall_dict(self.db.execute("SELECT * FROM status_history WHERE workflow_id = ? ORDER BY history_id", (workflow_id,)))
        return workflow

    def update_status(self, workflow_id: int, status: str, reason: str, ctx: RequestContext) -> dict[str, Any]:
        if status not in ALLOWED_STATUSES:
            raise ValueError("Invalid status")
        if len(reason) > MAX_REASON_LENGTH:
            raise ValueError(f"Reason must be at most {MAX_REASON_LENGTH} characters")
        current = self.db.fetchone_dict(self.db.execute("SELECT current_status, created_by FROM workflows WHERE workflow_id = ?", (workflow_id,)))
        if not current:
            raise KeyError("Workflow not found")
        if not self._has_permission(ctx, PERM_WORKFLOW_MANAGE_ALL) and current["created_by"] != ctx.user:
            raise PermissionError("Only the workflow creator or an Admin can update status")
        old = current["current_status"]
        self.db.execute("UPDATE workflows SET current_status = ?, updated_date = ? WHERE workflow_id = ?", (status, utc_now(), workflow_id))
        self.db.execute("INSERT INTO status_history(workflow_id, old_status, new_status, changed_by, changed_at, reason) VALUES (?, ?, ?, ?, ?, ?)", (workflow_id, old, status, ctx.user, utc_now(), reason))
        self._audit("workflow", str(workflow_id), "status_change", ctx.user, {"old": old, "new": status})
        if status in {"Rejected", "Cancelled", "Archived"}:
            self._notify(workflow_id, "WorkflowStatusChanged", [current["created_by"]], {"status": status})
        self.db.commit()
        return self.get_workflow(workflow_id, ctx)

    def set_hold(self, workflow_id: int, hold: bool, reason: str, ctx: RequestContext) -> dict[str, Any]:
        if not self._has_permission(ctx, PERM_WORKFLOW_MANAGE_ALL):
            raise PermissionError("Admin role required to set hold")
        row = self.db.fetchone_dict(self.db.execute("SELECT * FROM workflows WHERE workflow_id = ?", (workflow_id,)))
        if not row:
            raise KeyError("Workflow not found")
        self.db.execute("UPDATE workflows SET is_hold = ?, updated_date = ? WHERE workflow_id = ?", (1 if hold else 0, utc_now(), workflow_id))
        self._audit("workflow", str(workflow_id), "hold_set", ctx.user, {"hold": hold, "reason": reason})
        if hold:
            self._notify(workflow_id, "WorkflowHold", [row["created_by"]], {"reason": reason})
        self.db.commit()
        return self.get_workflow(workflow_id, ctx)

    def add_document(self, workflow_id: int, payload: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
        wf = self.db.fetchone_dict(self.db.execute("SELECT current_status, created_by FROM workflows WHERE workflow_id = ?", (workflow_id,)))
        if not wf:
            raise KeyError("Workflow not found")
        self._require_workflow_access(workflow_id, ctx, wf)
        self._store_document(workflow_id, payload, ctx, wf["current_status"])
        if payload.get("resubmission", False):
            self.db.execute("UPDATE workflows SET resubmitted = 1, current_status = 'In Review', updated_date = ? WHERE workflow_id = ?", (utc_now(), workflow_id))
            self.db.execute("INSERT INTO status_history(workflow_id, old_status, new_status, changed_by, changed_at, reason) VALUES (?, ?, ?, ?, ?, ?)", (workflow_id, wf["current_status"], "In Review", ctx.user, utc_now(), "Resubmission"))
        self.db.commit()
        return self.get_workflow(workflow_id, ctx)

    def decide_step(self, step_id: int, payload: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
        decision = payload["decision"]
        if decision not in {"Approve", "Reject"}:
            raise ValueError("Decision must be Approve or Reject")
        comment = str(payload.get("comment", ""))
        if len(comment) > MAX_COMMENT_LENGTH:
            raise ValueError(f"Comment must be at most {MAX_COMMENT_LENGTH} characters")
        step = self.db.fetchone_dict(self.db.execute("SELECT * FROM workflow_steps WHERE step_id = ?", (step_id,)))
        if not step:
            raise KeyError("Step not found")
        required_role = step["required_role"]
        if required_role not in ctx.roles and "Admin" not in ctx.roles:
            raise PermissionError(f"Role '{required_role}' is required to decide this step")

        self.db.execute("UPDATE workflow_steps SET step_status = ?, decision_by = ?, decision_date = ?, decision = ?, decision_comment = ? WHERE step_id = ?", ("Completed", ctx.user, utc_now(), decision, comment, step_id))
        self.db.execute("INSERT INTO approval_decisions(workflow_id, step_id, decision, comment, decided_by, decided_at) VALUES (?, ?, ?, ?, ?, ?)", (step["workflow_id"], step_id, decision, comment, ctx.user, utc_now()))
        self._audit("approval", str(step_id), "decide", ctx.user, {"decision": decision})

        workflow = self.db.fetchone_dict(self.db.execute("SELECT * FROM workflows WHERE workflow_id = ?", (step["workflow_id"],)))
        if decision == "Reject":
            self.db.execute("UPDATE workflows SET current_status = 'Rejected', resubmitted = 0, updated_date = ? WHERE workflow_id = ?", (utc_now(), step["workflow_id"]))
            self.db.execute("INSERT INTO status_history(workflow_id, old_status, new_status, changed_by, changed_at, reason) VALUES (?, ?, ?, ?, ?, ?)", (step["workflow_id"], workflow["current_status"], "Rejected", ctx.user, utc_now(), "Rejected by approver"))
            self._notify(step["workflow_id"], "WorkflowRejected", [workflow["created_by"]], {"comment": comment})
        else:
            pending = self.db.fetchone_dict(self.db.execute("SELECT COUNT(*) AS c FROM workflow_steps WHERE workflow_id = ? AND step_status = 'Pending'", (step["workflow_id"],)))
            if int(pending["c"]) == 0:
                self.db.execute("UPDATE workflows SET current_status = 'Archived', updated_date = ? WHERE workflow_id = ?", (utc_now(), step["workflow_id"]))
                self.db.execute("INSERT INTO status_history(workflow_id, old_status, new_status, changed_by, changed_at, reason) VALUES (?, ?, ?, ?, ?, ?)", (step["workflow_id"], workflow["current_status"], "Archived", ctx.user, utc_now(), "All approvals complete"))
                self._notify(step["workflow_id"], "WorkflowCompleted", [workflow["created_by"]], {})
        self.db.commit()
        return self.get_workflow(step["workflow_id"], ctx)

    def dashboard_summary(self, ctx: RequestContext) -> dict[str, Any]:
        if self._has_permission(ctx, PERM_DASHBOARD_FULL):
            status_ph = ",".join("?" for _ in IN_PROCESS_STATUSES)
            in_process = self.db.fetchone_dict(self.db.execute(f"SELECT COUNT(*) AS c FROM workflows WHERE current_status IN ({status_ph})", tuple(IN_PROCESS_STATUSES)))
            pending = self.db.fetchone_dict(self.db.execute("SELECT COUNT(*) AS c FROM workflow_steps WHERE step_status = 'Pending'"))
            rejected = self.db.fetchone_dict(self.db.execute("SELECT COUNT(*) AS c FROM workflows WHERE current_status = 'Rejected' AND resubmitted = 0"))
            return {"workflowsInProcess": int(in_process["c"]), "pendingApprovals": int(pending["c"]), "correctionQueue": int(rejected["c"])}
        visible_ids = self._visible_workflow_ids(ctx)
        if not visible_ids:
            return {"workflowsInProcess": 0, "pendingApprovals": 0, "correctionQueue": 0}
        id_ph = ",".join("?" for _ in visible_ids)
        status_ph = ",".join("?" for _ in IN_PROCESS_STATUSES)
        in_process = self.db.fetchone_dict(self.db.execute(
            f"SELECT COUNT(*) AS c FROM workflows WHERE workflow_id IN ({id_ph}) AND current_status IN ({status_ph})",
            tuple(visible_ids) + tuple(IN_PROCESS_STATUSES)))
        pending = self.db.fetchone_dict(self.db.execute(
            f"SELECT COUNT(*) AS c FROM workflow_steps WHERE workflow_id IN ({id_ph}) AND step_status = 'Pending'",
            tuple(visible_ids)))
        rejected = self.db.fetchone_dict(self.db.execute(
            f"SELECT COUNT(*) AS c FROM workflows WHERE workflow_id IN ({id_ph}) AND current_status = 'Rejected' AND resubmitted = 0",
            tuple(visible_ids)))
        return {"workflowsInProcess": int(in_process["c"]), "pendingApprovals": int(pending["c"]), "correctionQueue": int(rejected["c"])}

    def dashboard_pending(self, ctx: RequestContext) -> list[dict[str, Any]]:
        if self._has_permission(ctx, PERM_DASHBOARD_FULL):
            return self.db.fetchall_dict(
                self.db.execute(
                    """SELECT s.step_id, s.required_role, s.assigned_to, s.assigned_date, w.workflow_id, w.title
                       FROM workflow_steps s JOIN workflows w ON w.workflow_id = s.workflow_id
                       WHERE s.step_status = 'Pending' ORDER BY s.assigned_date"""
                )
            )
        conditions = ["s.assigned_to = ?"]
        params: list[Any] = [ctx.user]
        if ctx.roles:
            placeholders = ",".join("?" for _ in ctx.roles)
            conditions.append(f"s.required_role IN ({placeholders})")
            params.extend(ctx.roles)
        where = " OR ".join(conditions)
        return self.db.fetchall_dict(
            self.db.execute(
                f"""SELECT s.step_id, s.required_role, s.assigned_to, s.assigned_date, w.workflow_id, w.title
                    FROM workflow_steps s JOIN workflows w ON w.workflow_id = s.workflow_id
                    WHERE s.step_status = 'Pending' AND ({where}) ORDER BY s.assigned_date""",
                tuple(params),
            )
        )

    def dashboard_aging(self, ctx: RequestContext) -> list[dict[str, Any]]:
        thresholds = sorted(int(r["value"]) for r in self.db.fetchall_dict(self.db.execute("SELECT value FROM system_settings WHERE key LIKE 'aging_threshold_%'")))
        items: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        if self._has_permission(ctx, PERM_DASHBOARD_FULL):
            rows = self.db.fetchall_dict(self.db.execute("SELECT workflow_id, title, created_date, current_status FROM workflows"))
        else:
            visible_ids = self._visible_workflow_ids(ctx)
            if not visible_ids:
                return []
            id_ph = ",".join("?" for _ in visible_ids)
            rows = self.db.fetchall_dict(self.db.execute(
                f"SELECT workflow_id, title, created_date, current_status FROM workflows WHERE workflow_id IN ({id_ph})",
                tuple(visible_ids)))
        for row in rows:
            created = datetime.strptime(row["created_date"], ISO).replace(tzinfo=timezone.utc)
            days = (now - created).days
            level = max((t for t in thresholds if days >= t), default=0)
            if level > 0:
                items.append({"workflowId": row["workflow_id"], "title": row["title"], "daysOpen": days, "reminderLevel": level, "status": row["current_status"]})
        return items

    def run_aging_reminders(self, ctx: RequestContext) -> dict[str, Any]:
        self._require_admin(ctx)
        aging = self.dashboard_aging(ctx)
        pending_map = {p["workflow_id"]: p for p in self.dashboard_pending(ctx)}
        sent = 0
        for item in aging:
            wid = item["workflowId"]
            pending = pending_map.get(wid)
            if not pending:
                continue
            exists = self.db.fetchone_dict(self.db.execute("SELECT COUNT(*) AS c FROM reminder_log WHERE workflow_id = ? AND threshold_days = ?", (wid, item["reminderLevel"])))
            if int(exists["c"]) > 0:
                continue
            recipient = pending.get("assigned_to") or "unassigned"
            self._notify(wid, "AgingReminder", [recipient], item)
            self.db.execute("INSERT INTO reminder_log(workflow_id, step_id, threshold_days, reminded_at) VALUES (?, ?, ?, ?)", (wid, pending["step_id"], item["reminderLevel"], utc_now()))
            sent += 1
        self.db.commit()
        return {"sent": sent}

    def correction_queue(self, ctx: RequestContext) -> list[dict[str, Any]]:
        if self._has_permission(ctx, PERM_DASHBOARD_FULL):
            return self.db.fetchall_dict(self.db.execute("SELECT workflow_id, title, updated_date FROM workflows WHERE current_status = 'Rejected' AND resubmitted = 0 ORDER BY updated_date DESC"))
        return self.db.fetchall_dict(self.db.execute(
            "SELECT workflow_id, title, updated_date FROM workflows WHERE current_status = 'Rejected' AND resubmitted = 0 AND created_by = ? ORDER BY updated_date DESC",
            (ctx.user,)))

    def get_settings(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self.db.fetchall_dict(self.db.execute("SELECT key, value FROM system_settings ORDER BY key"))}

    def update_settings(self, payload: dict[str, Any], ctx: RequestContext) -> dict[str, str]:
        self._require_admin(ctx)
        invalid_keys = set(payload.keys()) - ALLOWED_SETTING_KEYS
        if invalid_keys:
            raise ValueError(f"Unknown setting keys: {', '.join(sorted(invalid_keys))}")
        for key, value in payload.items():
            self._upsert_setting(key, str(value))
        self._audit("system_settings", "global", "update", ctx.user, payload)
        self.db.commit()
        return self.get_settings()

    def list_roles(self) -> list[str]:
        return [r["role_name"] for r in self.db.fetchall_dict(self.db.execute("SELECT role_name FROM roles ORDER BY role_name"))]

    def create_role(self, payload: dict[str, Any], ctx: RequestContext) -> list[str]:
        self._require_admin(ctx)
        role = str(payload.get("roleName", "")).strip()
        if not role or len(role) > MAX_ROLE_NAME_LENGTH:
            raise ValueError(f"Role name is required and must be at most {MAX_ROLE_NAME_LENGTH} characters")
        if not re.match(r"^[A-Za-z0-9 ]+$", role):
            raise ValueError("Role name may only contain letters, digits, and spaces")
        exists = self.db.fetchone_dict(self.db.execute("SELECT role_name FROM roles WHERE role_name = ?", (role,)))
        if not exists:
            self.db.execute("INSERT INTO roles(role_name) VALUES (?)", (role,))
        self._audit("role", role, "create", ctx.user, payload)
        self.db.commit()
        return self.list_roles()

    def get_user_roles(self, user_name: str | None = None) -> list[dict[str, Any]]:
        if user_name:
            return self.db.fetchall_dict(self.db.execute("SELECT user_name, role_name FROM user_roles WHERE user_name = ? ORDER BY role_name", (user_name,)))
        return self.db.fetchall_dict(self.db.execute("SELECT user_name, role_name FROM user_roles ORDER BY user_name, role_name"))

    def update_user_roles(self, payload: dict[str, Any], ctx: RequestContext) -> list[dict[str, Any]]:
        self._require_admin(ctx)
        user = payload["userName"]
        roles = payload.get("roles", [])
        self.db.execute("DELETE FROM user_roles WHERE user_name = ?", (user,))
        for role in roles:
            self.db.execute("INSERT INTO user_roles(user_name, role_name) VALUES (?, ?)", (user, role))
        self._audit("user_role", user, "update", ctx.user, payload)
        self.db.commit()
        return self.get_user_roles(user)

    def get_notifications(self, workflow_id: int | None = None) -> list[dict[str, Any]]:
        if workflow_id is None:
            return self.db.fetchall_dict(self.db.execute("SELECT * FROM notifications ORDER BY notification_id DESC"))
        return self.db.fetchall_dict(self.db.execute("SELECT * FROM notifications WHERE workflow_id = ? ORDER BY notification_id DESC", (workflow_id,)))
