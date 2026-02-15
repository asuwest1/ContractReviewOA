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
    queue = svc.correction_queue(ctx)
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


# ---- RBAC Workflow Access Tests ----


def _create_test_workflow(svc, creator_ctx, title="Test WF", steps=None):
    """Helper to create a workflow with default steps."""
    if steps is None:
        steps = [{"requiredRole": "Technical", "assignedTo": "tech1"}]
    return svc.create_workflow({"title": title, "steps": steps}, creator_ctx)


def test_rbac_create_workflow_requires_permission(tmp_path):
    """Only roles with workflow:create permission can create workflows."""
    svc = make_service(tmp_path)
    # Customer Service can create
    cs = RequestContext(user="alice", roles={"Customer Service"})
    wf = svc.create_workflow({"title": "CS-Created", "steps": []}, cs)
    assert wf["workflow_id"] is not None

    # Admin can create
    admin = RequestContext(user="admin", roles={"Admin"})
    wf2 = svc.create_workflow({"title": "Admin-Created", "steps": []}, admin)
    assert wf2["workflow_id"] is not None

    # Technical role cannot create
    tech = RequestContext(user="tech1", roles={"Technical"})
    with pytest.raises(PermissionError, match="permission to create"):
        svc.create_workflow({"title": "Should Fail", "steps": []}, tech)

    # Commercial role cannot create
    comm = RequestContext(user="comm1", roles={"Commercial"})
    with pytest.raises(PermissionError, match="permission to create"):
        svc.create_workflow({"title": "Should Fail", "steps": []}, comm)

    # Legal role cannot create
    legal = RequestContext(user="legal1", roles={"Legal"})
    with pytest.raises(PermissionError, match="permission to create"):
        svc.create_workflow({"title": "Should Fail", "steps": []}, legal)


def test_rbac_list_workflows_admin_sees_all(tmp_path):
    """Admin sees all workflows regardless of involvement."""
    svc = make_service(tmp_path)
    cs = RequestContext(user="alice", roles={"Customer Service"})
    admin = RequestContext(user="admin", roles={"Admin"})

    svc.create_workflow({"title": "WF-1", "steps": []}, cs)
    svc.create_workflow({"title": "WF-2", "steps": []}, cs)

    workflows = svc.list_workflows(admin)
    assert len(workflows) == 2


def test_rbac_list_workflows_creator_sees_own(tmp_path):
    """Creator can see their own workflows."""
    svc = make_service(tmp_path)
    alice = RequestContext(user="alice", roles={"Customer Service"})
    bob = RequestContext(user="bob", roles={"Customer Service"})

    svc.create_workflow({"title": "Alice-WF", "steps": []}, alice)
    svc.create_workflow({"title": "Bob-WF", "steps": []}, bob)

    alice_wfs = svc.list_workflows(alice)
    assert len(alice_wfs) == 1
    assert alice_wfs[0]["title"] == "Alice-WF"

    bob_wfs = svc.list_workflows(bob)
    assert len(bob_wfs) == 1
    assert bob_wfs[0]["title"] == "Bob-WF"


def test_rbac_list_workflows_participant_sees_involved(tmp_path):
    """Users assigned to steps or with matching roles can see workflows."""
    svc = make_service(tmp_path)
    cs = RequestContext(user="alice", roles={"Customer Service"})

    svc.create_workflow(
        {"title": "WF-Tech", "steps": [{"requiredRole": "Technical", "assignedTo": "tech1"}]},
        cs,
    )
    svc.create_workflow(
        {"title": "WF-Legal", "steps": [{"requiredRole": "Legal", "assignedTo": "legal1"}]},
        cs,
    )

    # tech1 (assigned to a step) should see WF-Tech
    tech = RequestContext(user="tech1", roles={"Technical"})
    tech_wfs = svc.list_workflows(tech)
    assert len(tech_wfs) == 1
    assert tech_wfs[0]["title"] == "WF-Tech"

    # Any user with Technical role should also see WF-Tech
    tech2 = RequestContext(user="tech2", roles={"Technical"})
    tech2_wfs = svc.list_workflows(tech2)
    assert len(tech2_wfs) == 1
    assert tech2_wfs[0]["title"] == "WF-Tech"


def test_rbac_list_workflows_unrelated_user_sees_nothing(tmp_path):
    """A user with no relationship to any workflow sees nothing."""
    svc = make_service(tmp_path)
    cs = RequestContext(user="alice", roles={"Customer Service"})
    svc.create_workflow(
        {"title": "WF-1", "steps": [{"requiredRole": "Technical", "assignedTo": "tech1"}]},
        cs,
    )

    stranger = RequestContext(user="stranger", roles={"Commercial"})
    wfs = svc.list_workflows(stranger)
    assert len(wfs) == 0


def test_rbac_get_workflow_access_denied(tmp_path):
    """Users without involvement cannot view workflow details."""
    svc = make_service(tmp_path)
    cs = RequestContext(user="alice", roles={"Customer Service"})
    wf = svc.create_workflow(
        {"title": "Secret-WF", "steps": [{"requiredRole": "Technical", "assignedTo": "tech1"}]},
        cs,
    )

    stranger = RequestContext(user="stranger", roles={"Commercial"})
    with pytest.raises(PermissionError, match="Access denied"):
        svc.get_workflow(wf["workflow_id"], stranger)


def test_rbac_get_workflow_creator_allowed(tmp_path):
    """Creator can view their own workflow."""
    svc = make_service(tmp_path)
    cs = RequestContext(user="alice", roles={"Customer Service"})
    wf = svc.create_workflow({"title": "My-WF", "steps": []}, cs)

    result = svc.get_workflow(wf["workflow_id"], cs)
    assert result["title"] == "My-WF"


def test_rbac_get_workflow_participant_allowed(tmp_path):
    """User assigned to a step can view the workflow."""
    svc = make_service(tmp_path)
    cs = RequestContext(user="alice", roles={"Customer Service"})
    wf = svc.create_workflow(
        {"title": "WF-Access", "steps": [{"requiredRole": "Technical", "assignedTo": "tech1"}]},
        cs,
    )

    tech = RequestContext(user="tech1", roles={"Technical"})
    result = svc.get_workflow(wf["workflow_id"], tech)
    assert result["title"] == "WF-Access"


def test_rbac_get_workflow_matching_role_allowed(tmp_path):
    """User with a matching role (not assigned) can view the workflow."""
    svc = make_service(tmp_path)
    cs = RequestContext(user="alice", roles={"Customer Service"})
    wf = svc.create_workflow(
        {"title": "WF-Role", "steps": [{"requiredRole": "Legal", "assignedTo": "legal1"}]},
        cs,
    )

    # Different user with Legal role can see it
    legal2 = RequestContext(user="legal2", roles={"Legal"})
    result = svc.get_workflow(wf["workflow_id"], legal2)
    assert result["title"] == "WF-Role"


def test_rbac_update_status_creator_allowed(tmp_path):
    """Creator can update status on their own workflow."""
    svc = make_service(tmp_path)
    cs = RequestContext(user="alice", roles={"Customer Service"})
    wf = svc.create_workflow({"title": "Status-WF", "steps": []}, cs)

    result = svc.update_status(wf["workflow_id"], "Active", "Starting", cs)
    assert result["current_status"] == "Active"


def test_rbac_update_status_non_creator_denied(tmp_path):
    """Non-creator, non-admin users cannot update workflow status."""
    svc = make_service(tmp_path)
    cs = RequestContext(user="alice", roles={"Customer Service"})
    wf = svc.create_workflow(
        {"title": "Status-WF", "steps": [{"requiredRole": "Technical", "assignedTo": "tech1"}]},
        cs,
    )

    tech = RequestContext(user="tech1", roles={"Technical"})
    with pytest.raises(PermissionError, match="creator or an Admin"):
        svc.update_status(wf["workflow_id"], "Active", "Trying", tech)


def test_rbac_update_status_admin_allowed(tmp_path):
    """Admin can update status on any workflow."""
    svc = make_service(tmp_path)
    cs = RequestContext(user="alice", roles={"Customer Service"})
    wf = svc.create_workflow({"title": "Admin-Status", "steps": []}, cs)

    admin = RequestContext(user="admin", roles={"Admin"})
    result = svc.update_status(wf["workflow_id"], "Cancelled", "Admin override", admin)
    assert result["current_status"] == "Cancelled"


def test_rbac_set_hold_admin_only(tmp_path):
    """Only Admin can set hold on workflows."""
    svc = make_service(tmp_path)
    cs = RequestContext(user="alice", roles={"Customer Service"})
    wf = svc.create_workflow({"title": "Hold-WF", "steps": []}, cs)

    # Creator cannot hold
    with pytest.raises(PermissionError, match="Admin role required"):
        svc.set_hold(wf["workflow_id"], True, "Hold please", cs)

    # Technical cannot hold
    tech = RequestContext(user="tech1", roles={"Technical"})
    with pytest.raises(PermissionError, match="Admin role required"):
        svc.set_hold(wf["workflow_id"], True, "Hold", tech)

    # Admin can hold
    admin = RequestContext(user="admin", roles={"Admin"})
    result = svc.set_hold(wf["workflow_id"], True, "Admin hold", admin)
    assert result["is_hold"] == 1


def test_rbac_add_document_requires_access(tmp_path):
    """Only participants can add documents to a workflow."""
    svc = make_service(tmp_path)
    cs = RequestContext(user="alice", roles={"Customer Service"})
    wf = svc.create_workflow(
        {"title": "Doc-WF", "steps": [{"requiredRole": "Technical", "assignedTo": "tech1"}]},
        cs,
    )

    # Unrelated user cannot add document
    stranger = RequestContext(user="stranger", roles={"Commercial"})
    with pytest.raises(PermissionError, match="Access denied"):
        svc.add_document(wf["workflow_id"], {"filename": "evil.txt", "content": "x"}, stranger)

    # Creator can add document
    svc.add_document(wf["workflow_id"], {"filename": "creator.txt", "content": "ok"}, cs)

    # Assigned user can add document
    tech = RequestContext(user="tech1", roles={"Technical"})
    svc.add_document(wf["workflow_id"], {"filename": "tech.txt", "content": "ok", "version": 2}, tech)


def test_rbac_dashboard_summary_filtered(tmp_path):
    """Dashboard summary counts are filtered by visibility for non-admin users."""
    svc = make_service(tmp_path)
    alice = RequestContext(user="alice", roles={"Customer Service"})
    bob = RequestContext(user="bob", roles={"Customer Service"})
    admin = RequestContext(user="admin", roles={"Admin"})

    svc.create_workflow({"title": "Alice-WF", "steps": []}, alice)
    svc.create_workflow({"title": "Bob-WF", "steps": []}, bob)

    # Admin sees both
    admin_summary = svc.dashboard_summary(admin)
    assert admin_summary["workflowsInProcess"] == 2

    # Alice sees only her own
    alice_summary = svc.dashboard_summary(alice)
    assert alice_summary["workflowsInProcess"] == 1


def test_rbac_dashboard_pending_filtered(tmp_path):
    """Dashboard pending shows only steps relevant to the user's role or assignment."""
    svc = make_service(tmp_path)
    cs = RequestContext(user="alice", roles={"Customer Service"})
    admin = RequestContext(user="admin", roles={"Admin"})

    svc.create_workflow(
        {"title": "Multi-Step", "steps": [
            {"requiredRole": "Technical", "assignedTo": "tech1"},
            {"requiredRole": "Legal", "assignedTo": "legal1"},
        ]},
        cs,
    )

    # Admin sees all pending steps
    admin_pending = svc.dashboard_pending(admin)
    assert len(admin_pending) == 2

    # Technical user sees only Technical steps
    tech = RequestContext(user="tech1", roles={"Technical"})
    tech_pending = svc.dashboard_pending(tech)
    assert len(tech_pending) == 1
    assert tech_pending[0]["required_role"] == "Technical"

    # Legal user sees only Legal steps
    legal = RequestContext(user="legal1", roles={"Legal"})
    legal_pending = svc.dashboard_pending(legal)
    assert len(legal_pending) == 1
    assert legal_pending[0]["required_role"] == "Legal"


def test_rbac_correction_queue_filtered(tmp_path):
    """Correction queue shows only user's rejected workflows for non-admin."""
    svc = make_service(tmp_path)
    alice = RequestContext(user="alice", roles={"Customer Service"})
    bob = RequestContext(user="bob", roles={"Customer Service"})
    admin = RequestContext(user="admin", roles={"Admin"})

    wf_alice = svc.create_workflow(
        {"title": "Alice-Rejected", "steps": [{"requiredRole": "Technical", "assignedTo": "tech1"}]},
        alice,
    )
    wf_bob = svc.create_workflow(
        {"title": "Bob-Rejected", "steps": [{"requiredRole": "Technical", "assignedTo": "tech2"}]},
        bob,
    )

    tech = RequestContext(user="tech1", roles={"Technical"})
    svc.decide_step(wf_alice["steps"][0]["step_id"], {"decision": "Reject", "comment": "no"}, tech)
    tech2 = RequestContext(user="tech2", roles={"Technical"})
    svc.decide_step(wf_bob["steps"][0]["step_id"], {"decision": "Reject", "comment": "no"}, tech2)

    # Admin sees all rejected
    admin_queue = svc.correction_queue(admin)
    assert len(admin_queue) == 2

    # Alice sees only her own
    alice_queue = svc.correction_queue(alice)
    assert len(alice_queue) == 1
    assert alice_queue[0]["title"] == "Alice-Rejected"

    # Bob sees only his own
    bob_queue = svc.correction_queue(bob)
    assert len(bob_queue) == 1
    assert bob_queue[0]["title"] == "Bob-Rejected"


def test_rbac_nonexistent_workflow_returns_not_found(tmp_path):
    """Accessing a non-existent workflow returns KeyError (404), not PermissionError."""
    svc = make_service(tmp_path)
    admin = RequestContext(user="admin", roles={"Admin"})
    with pytest.raises(KeyError, match="not found"):
        svc.get_workflow(9999, admin)


def test_rbac_multi_role_user(tmp_path):
    """User with multiple roles gets union of visibility."""
    svc = make_service(tmp_path)
    cs = RequestContext(user="alice", roles={"Customer Service"})

    svc.create_workflow(
        {"title": "WF-Tech", "steps": [{"requiredRole": "Technical", "assignedTo": "tech1"}]},
        cs,
    )
    svc.create_workflow(
        {"title": "WF-Legal", "steps": [{"requiredRole": "Legal", "assignedTo": "legal1"}]},
        cs,
    )

    # User with both Technical and Legal roles sees both workflows
    multi = RequestContext(user="multi", roles={"Technical", "Legal"})
    wfs = svc.list_workflows(multi)
    assert len(wfs) == 2


def test_rbac_dashboard_aging_filtered(tmp_path):
    """Dashboard aging is filtered by visibility for non-admin users."""
    svc = make_service(tmp_path)
    alice = RequestContext(user="alice", roles={"Customer Service"})
    bob = RequestContext(user="bob", roles={"Customer Service"})
    admin = RequestContext(user="admin", roles={"Admin"})

    wf_alice = svc.create_workflow({"title": "Alice-Aging", "steps": []}, alice)
    wf_bob = svc.create_workflow({"title": "Bob-Aging", "steps": []}, bob)

    # Make both workflows old enough to trigger aging
    svc.db.execute("UPDATE workflows SET created_date = ? WHERE workflow_id = ?", ("2000-01-01T00:00:00Z", wf_alice["workflow_id"]))
    svc.db.execute("UPDATE workflows SET created_date = ? WHERE workflow_id = ?", ("2000-01-01T00:00:00Z", wf_bob["workflow_id"]))
    svc.db.commit()

    # Admin sees both
    admin_aging = svc.dashboard_aging(admin)
    assert len(admin_aging) == 2

    # Alice sees only her own
    alice_aging = svc.dashboard_aging(alice)
    assert len(alice_aging) == 1
    assert alice_aging[0]["title"] == "Alice-Aging"
