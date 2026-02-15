IF OBJECT_ID('workflows', 'U') IS NULL
CREATE TABLE workflows (
  workflow_id INT IDENTITY(1,1) PRIMARY KEY,
  title NVARCHAR(255) NOT NULL,
  doc_type NVARCHAR(50) NOT NULL,
  current_status NVARCHAR(50) NOT NULL,
  is_hold BIT NOT NULL DEFAULT 0,
  resubmitted BIT NOT NULL DEFAULT 0,
  created_date NVARCHAR(30) NOT NULL,
  updated_date NVARCHAR(30) NOT NULL,
  created_by NVARCHAR(255) NOT NULL
);

IF OBJECT_ID('workflow_documents', 'U') IS NULL
CREATE TABLE workflow_documents (
  doc_id INT IDENTITY(1,1) PRIMARY KEY,
  workflow_id INT NOT NULL,
  file_path NVARCHAR(500) NOT NULL,
  is_golden BIT NOT NULL DEFAULT 0,
  version INT NOT NULL,
  note NVARCHAR(MAX),
  uploaded_by NVARCHAR(255) NOT NULL,
  uploaded_at NVARCHAR(30) NOT NULL,
  FOREIGN KEY(workflow_id) REFERENCES workflows(workflow_id)
);

IF OBJECT_ID('workflow_steps', 'U') IS NULL
CREATE TABLE workflow_steps (
  step_id INT IDENTITY(1,1) PRIMARY KEY,
  workflow_id INT NOT NULL,
  required_role NVARCHAR(100) NOT NULL,
  sequence_order INT NOT NULL,
  parallel_group INT NOT NULL DEFAULT 0,
  step_status NVARCHAR(50) NOT NULL,
  assigned_to NVARCHAR(255),
  assigned_date NVARCHAR(30),
  decision_by NVARCHAR(255),
  decision_date NVARCHAR(30),
  decision NVARCHAR(30),
  decision_comment NVARCHAR(MAX),
  FOREIGN KEY(workflow_id) REFERENCES workflows(workflow_id)
);

IF OBJECT_ID('approval_decisions', 'U') IS NULL
CREATE TABLE approval_decisions (
  decision_id INT IDENTITY(1,1) PRIMARY KEY,
  workflow_id INT NOT NULL,
  step_id INT NOT NULL,
  decision NVARCHAR(30) NOT NULL,
  comment NVARCHAR(MAX),
  decided_by NVARCHAR(255) NOT NULL,
  decided_at NVARCHAR(30) NOT NULL
);

IF OBJECT_ID('status_history', 'U') IS NULL
CREATE TABLE status_history (
  history_id INT IDENTITY(1,1) PRIMARY KEY,
  workflow_id INT NOT NULL,
  old_status NVARCHAR(50),
  new_status NVARCHAR(50) NOT NULL,
  changed_by NVARCHAR(255) NOT NULL,
  changed_at NVARCHAR(30) NOT NULL,
  reason NVARCHAR(MAX)
);

IF OBJECT_ID('system_settings', 'U') IS NULL
CREATE TABLE system_settings (
  [key] NVARCHAR(100) PRIMARY KEY,
  [value] NVARCHAR(100) NOT NULL
);

IF OBJECT_ID('roles', 'U') IS NULL
CREATE TABLE roles (
  role_name NVARCHAR(100) PRIMARY KEY
);

IF OBJECT_ID('user_roles', 'U') IS NULL
CREATE TABLE user_roles (
  user_name NVARCHAR(255) NOT NULL,
  role_name NVARCHAR(100) NOT NULL,
  PRIMARY KEY(user_name, role_name)
);

IF OBJECT_ID('notifications', 'U') IS NULL
CREATE TABLE notifications (
  notification_id INT IDENTITY(1,1) PRIMARY KEY,
  workflow_id INT,
  event NVARCHAR(80) NOT NULL,
  recipient NVARCHAR(255) NOT NULL,
  created_at NVARCHAR(30) NOT NULL,
  payload NVARCHAR(MAX)
);

IF OBJECT_ID('audit_log', 'U') IS NULL
CREATE TABLE audit_log (
  audit_id INT IDENTITY(1,1) PRIMARY KEY,
  entity_type NVARCHAR(80) NOT NULL,
  entity_id NVARCHAR(80) NOT NULL,
  action NVARCHAR(80) NOT NULL,
  actor NVARCHAR(255) NOT NULL,
  details NVARCHAR(MAX),
  created_at NVARCHAR(30) NOT NULL
);

IF OBJECT_ID('reminder_log', 'U') IS NULL
CREATE TABLE reminder_log (
  reminder_id INT IDENTITY(1,1) PRIMARY KEY,
  workflow_id INT NOT NULL,
  step_id INT,
  threshold_days INT NOT NULL,
  reminded_at NVARCHAR(30) NOT NULL
);
