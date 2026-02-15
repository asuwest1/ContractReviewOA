# Contract Review OA User Documentation

This guide explains how business and admin users can operate the web UI.

## Accessing the application

1. Start the backend server.
2. Open `http://localhost:8000` in your browser.
3. In the header section:
   - Enter your user identity in **User**.
   - Enter one or more comma-separated roles in **Roles**.
   - Click **Refresh**.

> In local development, these values are sent as `X-Remote-User` and `X-User-Roles` headers.

---

## Create a workflow

1. In **Create Workflow**:
   - Enter a title.
   - Choose document type (`PO` or `Contract`).
   - Add initial document content.
2. Click **Create**.

The app creates a workflow with initial approval steps and one initial golden document version.

---

## Use the dashboard

The **Dashboard** section provides:
- **Summary**: workflow counts and status overview.
- **Pending Approvals**: approval actions waiting by role/user.
- **Aging Items**: workflows open long enough to trigger reminders.

Admins can click **Run Aging Reminders (Admin)** to execute reminders immediately.

---

## Browse and select workflows

1. In **Workflows**, click a workflow ID button.
2. The selection appears in **Workflow Actions** and full JSON details appear in **Workflow Detail**.

---

## Workflow actions

After selecting a workflow, you can:

### Update status
1. Pick a value in the status dropdown.
2. Optionally add a reason.
3. Click **Update Status**.

### Place or release HOLD
1. Choose **Set HOLD** or **Release HOLD**.
2. Optionally add a reason.
3. Click **Apply HOLD**.

### Add a document version
1. Enter filename and version.
2. Optionally mark as **Golden** and/or **Resubmission**.
3. Enter document content.
4. Click **Add Document**.

---

## Approval decisions

In **Pending Steps (Approve/Reject)**:
1. Click **Approve** or **Reject** for a step.
2. Enter an optional comment when prompted.
3. The workflow and dashboard refresh after submission.

---

## Admin settings

In **Admin Settings**:
1. Set values for `aging_threshold_1` through `aging_threshold_5`.
2. Click **Save Settings**.

These thresholds determine reminder escalation behavior in aging workflows.

---

## Operational tips

- Use **Refresh** to reload dashboard and workflow lists after external changes.
- Ensure your role list includes required roles (for example, `Admin`, `Technical`, `Commercial`) to perform privileged actions.
- If actions fail, check error alerts in the UI and verify user/role values.
