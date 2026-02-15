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
