-- hr_assistant plugin 操作类工具 — 6 张业务表
-- v2.0 — 真实持久化 + 状态机 + 审计

-- 1. 请假申请
CREATE TABLE IF NOT EXISTS hr_leave_requests (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id      VARCHAR(32) NOT NULL UNIQUE,    -- L20260808-001
    user_id         VARCHAR(64) NOT NULL,
    leave_type      VARCHAR(16) NOT NULL,           -- annual / sick / personal / marriage / maternity / bereavement / compensatory
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    days            DECIMAL(3,1) NOT NULL,         -- 0.5/1.0/2.5
    reason          VARCHAR(512) NOT NULL,
    status          VARCHAR(16) NOT NULL DEFAULT 'pending',  -- pending/approved/rejected/cancelled
    approver_id     VARCHAR(64),
    approval_note   VARCHAR(512),
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user (user_id),
    INDEX idx_status (status),
    INDEX idx_dates (start_date, end_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. 报销申请
CREATE TABLE IF NOT EXISTS hr_reimbursements (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id      VARCHAR(32) NOT NULL UNIQUE,    -- R20260808-001
    user_id         VARCHAR(64) NOT NULL,
    category        VARCHAR(32) NOT NULL,           -- travel / office / training / meal / other
    amount          DECIMAL(10,2) NOT NULL,
    currency        VARCHAR(8) NOT NULL DEFAULT 'CNY',
    description     VARCHAR(512) NOT NULL,
    invoice_url     VARCHAR(512),
    status          VARCHAR(16) NOT NULL DEFAULT 'pending',
    approver_id     VARCHAR(64),
    approval_note   VARCHAR(512),
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user (user_id),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. 证明申请
CREATE TABLE IF NOT EXISTS hr_certificates (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id      VARCHAR(32) NOT NULL UNIQUE,    -- C20260808-001
    user_id         VARCHAR(64) NOT NULL,
    cert_type       VARCHAR(32) NOT NULL,           -- employment / income / separation / work_permit
    purpose         VARCHAR(256) NOT NULL,
    language        VARCHAR(8) NOT NULL DEFAULT 'zh',
    quantity        INT NOT NULL DEFAULT 1,
    status          VARCHAR(16) NOT NULL DEFAULT 'pending',
    deliver_method  VARCHAR(16) NOT NULL DEFAULT 'email',  -- email / pickup / mail
    delivery_addr   VARCHAR(512),
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. 资产申请
CREATE TABLE IF NOT EXISTS hr_asset_requests (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id      VARCHAR(32) NOT NULL UNIQUE,    -- A20260808-001
    user_id         VARCHAR(64) NOT NULL,
    asset_type      VARCHAR(32) NOT NULL,           -- laptop / monitor / keyboard / mouse / headset / phone / other
    sku             VARCHAR(64),
    reason          VARCHAR(512) NOT NULL,
    estimated_cost  DECIMAL(10,2),
    status          VARCHAR(16) NOT NULL DEFAULT 'pending',
    approver_id     VARCHAR(64),
    approval_note   VARCHAR(512),
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. 培训报名
CREATE TABLE IF NOT EXISTS hr_training_registrations (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id      VARCHAR(32) NOT NULL UNIQUE,    -- T20260808-001
    user_id         VARCHAR(64) NOT NULL,
    training_name   VARCHAR(128) NOT NULL,
    training_type   VARCHAR(16) NOT NULL,           -- external / internal / certification
    provider        VARCHAR(128),
    expected_cost   DECIMAL(10,2),
    expected_date   DATE,
    business_relevance VARCHAR(512),
    status          VARCHAR(16) NOT NULL DEFAULT 'pending',
    approver_id     VARCHAR(64),
    approval_note   VARCHAR(512),
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. 转正申请
CREATE TABLE IF NOT EXISTS hr_regularization (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id      VARCHAR(32) NOT NULL UNIQUE,    -- P20260808-001
    user_id         VARCHAR(64) NOT NULL,
    probation_start DATE NOT NULL,
    probation_end   DATE NOT NULL,
    achievements    TEXT NOT NULL,
    self_assessment TEXT,
    status          VARCHAR(16) NOT NULL DEFAULT 'pending',
    approver_id     VARCHAR(64),
    approval_note   VARCHAR(512),
    defense_date    DATE,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 7. 审计日志(所有操作类工具都写)
CREATE TABLE IF NOT EXISTS hr_audit_log (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id      VARCHAR(32),
    user_id         VARCHAR(64) NOT NULL,
    action          VARCHAR(64) NOT NULL,           -- submit_leave / approve_leave / reject_leave / ...
    entity_type     VARCHAR(32) NOT NULL,           -- leave / reimbursement / certificate / ...
    entity_id       VARCHAR(64),
    detail          TEXT,
    trace_id        VARCHAR(64),
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user (user_id),
    INDEX idx_action (action),
    INDEX idx_request (request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
