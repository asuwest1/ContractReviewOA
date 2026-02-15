# Code Requirements Plan

## Repository Review Summary

The repository currently contains two business-facing requirement artifacts:

1. `ProductRequirementsDocument` with high-level product, workflow, API, and database expectations.
2. `UAT Requirements` with test scenarios and acceptance checks.

There is no application source code yet, so the immediate requirement is to convert these documents into an implementation-ready technical backlog.

## Version 1 Decisions (Confirmed)

The following V1 requirements are confirmed and should be treated as in-scope constraints for implementation:

- Include **approvals and audit** capabilities in V1 (not deferred).
- Implement **all defined workflow statuses** in V1: `Active`, `Reviewing`, `Negotiating`, `Archived`, `In Review`, `Rejected`, `Cancelled`.
- Support **parallel and sequential routing** in V1.
- Include **HOLD logic** in V1, but release from HOLD is **not strictly gated** on new version upload only.
- Use **Integrated Authentication** with AD (Windows Integrated Auth model).
- Use UNC document storage path format: `\\FQDN\{subfolder}\`, where lifecycle subfolders are status-driven:
  - `\InProcess`
  - `\Approved`
  - `\Cancelled`
  - `\Rejected`
- Enforce **only one Golden PO/master document** per workflow.
- Ship **workflow launch/rejection/completion notifications and aging reminders** in V1.
- Deliver **full dashboard scope** in V1: active workflows, pending approvals, aging, correction queue.
- Require **append-only audit coverage** in V1 for approvals and status changes with user identity and timestamp.

## Functional Requirements to Implement

### 1) Identity and Access
- Integrate authentication with Active Directory (AD) using Integrated Authentication.
- Support role-based access control for at least: Customer Service, Technical, Commercial, Legal, and Admin.
- Allow admin assignment of AD users to business roles.

### 2) Workflow Lifecycle
- Create workflow records for PO/Contract review.
- Support statuses: `Active`, `Reviewing`, `Negotiating`, `Archived`, `In Review`, `Rejected`, `Cancelled`.
- Support parallel and sequential approval routing.
- Allow retrospective registration of existing PO/Contract records as `In Review`.
- Implement HOLD behavior tied to discrepancy handling.

### 3) Document Management
- Upload and store attachments in a secure Windows file share path.
- Track exactly one designated `Golden PO`/master contract per workflow.
- Support versioning and amendment notes.
- Ensure HOLD release supports approved resolution actions and is not strictly limited to document re-upload.
- Route file placement by workflow state using UNC folder partitions: `InProcess`, `Approved`, `Cancelled`, `Rejected`.

### 4) Approvals and Auditability
- Capture decision events (approve/reject) with user identity and timestamp.
- Record full status transition history.
- Preserve immutable append-only audit entries for compliance.

### 5) Notifications and Aging
- SMTP notifications on workflow creation, rejection, completion.
- Configurable aging thresholds (5 values such as 2, 5, 10, 15, 30 days).
- Reminder engine to notify pending approvers based on threshold crossings.

### 6) Dashboard and Reporting
- Active workflows overview.
- Pending approvals by role/user.
- Aging views by reminder tier.
- Correction queue for rejected-not-resubmitted workflows.

### 7) Administration
- CRUD for system settings (including threshold values).
- Role management and user-role mapping UI/API.

## Non-Functional Requirements

- IIS-compatible deployment on Windows Server 2019.
- SQL Server 2019 compatibility.
- Secure AD-integrated authentication and authorization.
- Reliable file share access with resilient error handling.
- Traceability suitable for internal audits.
- UNC storage compatibility using `\\FQDN\{subfolder}\` pathing conventions.

## Suggested Initial Architecture

- **Frontend:** Browser SPA (React or similar).
- **Backend API:** ASP.NET Core Web API (recommended for IIS + AD ecosystem).
- **Database:** SQL Server 2019 with migration tooling.
- **Background Jobs:** Hosted service / scheduler for aging reminders.
- **Storage Adapter:** Service abstraction for Windows file share operations.

## Minimum Viable Data Model (expanded from PRD)

- `Workflows`
- `WorkflowDocuments`
- `WorkflowSteps`
- `Users` (AD identity mapping + profile cache)
- `Roles`
- `UserRoles`
- `WorkflowAssignments`
- `ApprovalDecisions`
- `StatusHistory`
- `SystemSettings`
- `NotificationLog`

## API Backlog (Phase 1)

- `POST /api/workflows`
- `GET /api/workflows`
- `GET /api/workflows/{id}`
- `PUT /api/workflows/{id}/status`
- `PUT /api/workflows/{id}/hold`
- `POST /api/workflows/{id}/documents`
- `POST /api/approvals/{stepId}/decide`
- `GET /api/dashboard/summary`
- `GET /api/dashboard/aging`
- `GET /api/dashboard/correction-queue`
- `GET/PUT /api/admin/settings`
- `GET/POST /api/admin/roles`
- `GET/PUT /api/admin/user-roles`

## Implementation Plan by Milestones

### Milestone 0: Foundation
- Scaffold backend and frontend projects.
- Set up SQL schema migrations.
- Configure AD Integrated Authentication.
- Establish CI checks and environment configs.

### Milestone 1 (V1 Scope): Core Workflow + Upload + Approvals/Audit + Notifications + Dashboard
- Implement workflow creation and status transitions.
- Add file upload to status-driven Windows file share folders (`InProcess`, `Approved`, `Cancelled`, `Rejected`) with metadata persistence.
- Implement step assignments (parallel/sequential).
- Add decision endpoints and sign-off capture.
- Add immutable history logging.
- Implement discrepancy-triggered HOLD.
- Add threshold settings and background reminder service.
- Build dashboard widgets for active, pending, aging, correction.
- Implement rejection handling and correction queue.
- Ensure launch/rejection/completion notifications and aging reminders are emitted.

### Milestone 2: UAT Hardening
- Map UAT scenarios A-E to automated integration tests where possible.
- Execute manual UAT scripts with business testers.
- Produce release readiness checklist and sign-off artifacts.

## UAT-to-Engineering Traceability Matrix

- **Scenario A** -> Workflow creation + role assignment + initial notifications.
- **Scenario B** -> Parallel approvals + audit sign-off fields.
- **Scenario C** -> HOLD trigger and release conditions.
- **Scenario D** -> Rejection workflow + correction queue visibility.
- **Scenario E** -> Background aging reminders + dashboard indicators.

## Remaining Open Questions Before Coding

1. Preferred backend stack confirmation (ASP.NET Core assumed).
2. File share permissions model and service account strategy.
3. Required retention policy for audit logs and attachments.
4. SLA for reminder job execution frequency.
5. Exact notification templates and recipients per event type.
6. Whether contracts and POs need separate approval templates.

## Definition of Done (Initial Release)

- All Scenario A-E UAT tests pass.
- Audit logs capture all approvals/status changes with timestamps and user identity.
- Dashboard reflects real-time workflow/aging/correction metrics.
- Configurable aging thresholds persist and drive reminder behavior.
- Production deployment validated on Windows Server 2019 + IIS + SQL Server 2019.
