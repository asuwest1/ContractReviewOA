import os
import sys
from types import SimpleNamespace

import pytest

from contract_review.auth import AuthResolver
from contract_review.mailer import SmtpMailer
from contract_review.service import AppService, DatabaseError


class DummyHeaders(dict):
    def get(self, k, d=None):
        return super().get(k, d)


def test_auth_resolver_uses_integrated_env(monkeypatch):
    monkeypatch.setenv("REMOTE_USER", "CORP\\alice")
    monkeypatch.setenv("REMOTE_GROUPS", "Admin;Technical")
    monkeypatch.setenv("ALLOW_DEV_HEADERS", "false")
    ident = AuthResolver().resolve(DummyHeaders({"X-Remote-User": "ignored", "X-User-Roles": "ignored"}))
    assert ident.user == "CORP\\alice"
    assert "Admin" in ident.roles
    assert "Technical" in ident.roles


def test_smtp_mailer_disabled_without_host(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    mailer = SmtpMailer()
    assert mailer.enabled is False
    assert mailer.send_event("a@b.com", "Event", {}) is False


def test_mssql_provider_requires_pyodbc(monkeypatch, tmp_path):
    monkeypatch.setenv("CONTRACT_REVIEW_DB_PROVIDER", "mssql")
    monkeypatch.setenv("CONTRACT_REVIEW_MSSQL_CONNECTION", "Driver=x;Server=y;")
    # ensure import fails
    monkeypatch.setitem(sys.modules, "pyodbc", None)
    with pytest.raises(DatabaseError):
        AppService(storage_root=str(tmp_path / "storage"))


def test_mssql_provider_initializes_with_fake_pyodbc(monkeypatch, tmp_path):
    class FakeCursor:
        def __init__(self):
            self.description = [("c",)]
            self._fetch = [(0,)]

        def execute(self, sql, params=()):
            if "SELECT key FROM system_settings" in sql:
                self.description = [("key",)]
                self._fetch = []
            elif "SELECT role_name FROM roles" in sql:
                self.description = [("role_name",)]
                self._fetch = []
            elif "SELECT" in sql and "COUNT" in sql:
                self.description = [("c",)]
                self._fetch = [(0,)]
            return self

        def fetchone(self):
            if not self._fetch:
                return None
            return self._fetch.pop(0)

        def fetchall(self):
            out = list(self._fetch)
            self._fetch = []
            return out

    class FakeConn:
        def __init__(self):
            self.autocommit = False
            self.cursor_obj = FakeCursor()

        def cursor(self):
            return self.cursor_obj

        def commit(self):
            pass

        def rollback(self):
            pass

    fake_pyodbc = SimpleNamespace(connect=lambda _: FakeConn())
    monkeypatch.setitem(sys.modules, "pyodbc", fake_pyodbc)
    monkeypatch.setenv("CONTRACT_REVIEW_DB_PROVIDER", "mssql")
    monkeypatch.setenv("CONTRACT_REVIEW_MSSQL_CONNECTION", "Driver=x;Server=y;")

    svc = AppService(storage_root=str(tmp_path / "storage"))
    assert svc.db.provider == "mssql"
