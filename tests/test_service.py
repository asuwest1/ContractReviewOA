import pytest

from contract_review.service import AppService, RequestContext


def make_service(tmp_path):
    return AppService(db_provider="sqlite", connection_string=str(tmp_path / "test.db"), storage_root=str(tmp_path / "storage"))


def test_workflow_creation_with_golden_and_steps(tmp_path):
    svc = make_service(tmp_path)
    ctx = RequestContext(user="alice", roles={"Customer Service"})

    wf = svc.create_workflow(
        {
            "title": "PO-100",
            "docType": "PO",
            "steps": [
                {"requiredRole": "Technical", "sequenceOrder": 1, "assignedTo": "tech1", "parallelGroup": 1},
                {"requiredRole": "Commercial", "sequenceOrder": 1, "assignedTo": "comm1", "parallelGroup": 1},
            ],
            "document": {"filename": "po.txt", "content": "hello", "isGolden": True, "version": 1},
        },
        ctx,
    )

    assert wf["current_status"] == "Reviewing"
    assert len(wf["steps"]) == 2
    assert len(wf["documents"]) == 1
    assert wf["documents"][0]["is_golden"] == 1


def test_single_golden_rule(tmp_path):
    svc = make_service(tmp_path)
    ctx = RequestContext(user="alice", roles={"Customer Service"})
    wf = svc.create_workflow({"title": "Contract-1", "steps": []}, ctx)

    svc.add_document(wf["workflow_id"], {"filename": "a.txt", "isGolden": True, "version": 1}, ctx)
    try:
        svc.add_document(wf["workflow_id"], {"filename": "b.txt", "isGolden": True, "version": 2}, ctx)
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_reject_flows_to_correction_queue(tmp_path):
    svc = make_service(tmp_path)
    ctx = RequestContext(user="alice", roles={"Customer Service"})
    wf = svc.create_workflow(
        {
            "title": "PO-200",
            "steps": [{"requiredRole": "Technical", "assignedTo": "tech1"}],
        },
        ctx,
    )
    step_id = wf["steps"][0]["step_id"]
    approver = RequestContext(user="tech1", roles={"Technical"})
    updated = svc.decide_step(step_id, {"decision": "Reject", "comment": "Mismatch"}, approver)

    assert updated["current_status"] == "Rejected"
    queue = svc.correction_queue()
    assert any(item["workflow_id"] == wf["workflow_id"] for item in queue)


def test_admin_settings_and_reminders(tmp_path):
    svc = make_service(tmp_path)
    non_admin = RequestContext(user="bob", roles={"Technical"})
    admin = RequestContext(user="admin", roles={"Admin"})

    forbidden = False
    try:
        svc.update_settings({"aging_threshold_1": 0}, non_admin)
    except PermissionError:
        forbidden = True
    assert forbidden

    settings = svc.update_settings({"aging_threshold_1": 1}, admin)
    assert settings["aging_threshold_1"] == "1"

    wf = svc.create_workflow(
        {"title": "Aging Item", "steps": [{"requiredRole": "Technical", "assignedTo": "tech1"}]},
        RequestContext(user="alice", roles={"Customer Service"}),
    )
    svc.db.execute("UPDATE workflows SET created_date = ? WHERE workflow_id = ?", ("2000-01-01T00:00:00Z", wf["workflow_id"]))
    svc.db.commit()
    reminders = svc.run_aging_reminders(admin)
    assert reminders["sent"] >= 1
    notifications = svc.get_notifications(wf["workflow_id"])
    assert any(n["event"] == "AgingReminder" for n in notifications)


def test_add_document_rejects_path_traversal_filename(tmp_path):
    svc = make_service(tmp_path)
    ctx = RequestContext(user="alice", roles={"Customer Service"})
    wf = svc.create_workflow({"title": "Contract-2", "steps": []}, ctx)

    raised = False
    try:
        svc.add_document(wf["workflow_id"], {"filename": "../outside.txt", "content": "x"}, ctx)
    except ValueError:
        raised = True
    assert raised


# ---- V2 Security Tests ----


def test_decide_step_requires_matching_role(tmp_path):
    """V2-01: User without the step's required_role cannot approve/reject."""
    svc = make_service(tmp_path)
    ctx = RequestContext(user="alice", roles={"Customer Service"})
    wf = svc.create_workflow(
        {"title": "PO-Role", "steps": [{"requiredRole": "Technical", "assignedTo": "tech1"}]},
        ctx,
    )
    step_id = wf["steps"][0]["step_id"]
    # User with wrong role should be denied
    wrong_role = RequestContext(user="bob", roles={"Commercial"})
    with pytest.raises(PermissionError):
        svc.decide_step(step_id, {"decision": "Approve"}, wrong_role)
    # User with correct role should succeed
    correct_role = RequestContext(user="tech1", roles={"Technical"})
    result = svc.decide_step(step_id, {"decision": "Approve"}, correct_role)
    assert result["steps"][0]["decision"] == "Approve"


def test_decide_step_admin_can_override(tmp_path):
    """V2-01: Admin can decide any step regardless of required_role."""
    svc = make_service(tmp_path)
    ctx = RequestContext(user="alice", roles={"Customer Service"})
    wf = svc.create_workflow(
        {"title": "PO-Admin", "steps": [{"requiredRole": "Legal", "assignedTo": "legal1"}]},
        ctx,
    )
    step_id = wf["steps"][0]["step_id"]
    admin = RequestContext(user="admin", roles={"Admin"})
    result = svc.decide_step(step_id, {"decision": "Approve"}, admin)
    assert result["steps"][0]["decision"] == "Approve"


def test_create_workflow_rejects_invalid_doc_type(tmp_path):
    """V2 Input Validation: docType must be PO or Contract."""
    svc = make_service(tmp_path)
    ctx = RequestContext(user="alice", roles={"Customer Service"})
    with pytest.raises(ValueError, match="docType"):
        svc.create_workflow({"title": "Bad", "docType": "Invoice"}, ctx)


def test_create_workflow_rejects_long_title(tmp_path):
    """V2 Input Validation: title must be <= 255 chars."""
    svc = make_service(tmp_path)
    ctx = RequestContext(user="alice", roles={"Customer Service"})
    with pytest.raises(ValueError, match="Title"):
        svc.create_workflow({"title": "A" * 256}, ctx)


def test_create_workflow_rejects_empty_title(tmp_path):
    """V2 Input Validation: title must not be empty."""
    svc = make_service(tmp_path)
    ctx = RequestContext(user="alice", roles={"Customer Service"})
    with pytest.raises(ValueError, match="Title"):
        svc.create_workflow({"title": "   "}, ctx)


def test_settings_rejects_unknown_keys(tmp_path):
    """V2-05: Only aging_threshold_* keys are accepted."""
    svc = make_service(tmp_path)
    admin = RequestContext(user="admin", roles={"Admin"})
    with pytest.raises(ValueError, match="Unknown setting"):
        svc.update_settings({"evil_key": "pwned"}, admin)
    # Valid key should still work
    result = svc.update_settings({"aging_threshold_1": 3}, admin)
    assert result["aging_threshold_1"] == "3"


def test_add_document_rejects_null_byte_filename(tmp_path):
    """V2-06: Null bytes in filename are rejected."""
    svc = make_service(tmp_path)
    ctx = RequestContext(user="alice", roles={"Customer Service"})
    wf = svc.create_workflow({"title": "NullTest", "steps": []}, ctx)
    with pytest.raises(ValueError, match="Invalid filename"):
        svc.add_document(wf["workflow_id"], {"filename": "test\x00.txt", "content": "x"}, ctx)


def test_create_role_rejects_special_characters(tmp_path):
    """V2 Input Validation: role names only allow alphanumeric + spaces."""
    svc = make_service(tmp_path)
    admin = RequestContext(user="admin", roles={"Admin"})
    with pytest.raises(ValueError, match="letters"):
        svc.create_role({"roleName": "Admin<script>"}, admin)
    # Valid role should work
    result = svc.create_role({"roleName": "New Role"}, admin)
    assert "New Role" in result


def test_decide_step_rejects_long_comment(tmp_path):
    """V2 Input Validation: comment must be <= 2000 chars."""
    svc = make_service(tmp_path)
    ctx = RequestContext(user="alice", roles={"Customer Service"})
    wf = svc.create_workflow(
        {"title": "PO-Comment", "steps": [{"requiredRole": "Technical", "assignedTo": "tech1"}]},
        ctx,
    )
    step_id = wf["steps"][0]["step_id"]
    tech = RequestContext(user="tech1", roles={"Technical"})
    with pytest.raises(ValueError, match="Comment"):
        svc.decide_step(step_id, {"decision": "Approve", "comment": "x" * 2001}, tech)
