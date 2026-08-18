-- ============================================================
-- Phase 4 Observability: call_records
--
-- call_records 保存每次调用的 span(trace_id / span_id / parent_span_id / name /
--   ts_start / ts_end / duration_ms / status / attributes_json / error_message /
--   user_id / tenant_id)。
--
-- 与 auth_audit_log(Phase 3 RBAC 安全审计)严格独立:
--   auth_audit_log 写失败 fail-closed (raise HTTPException 500)
--   call_records    写失败 warning 不阻断业务 (见 call_record.py)
-- ============================================================

CREATE TABLE IF NOT EXISTS call_records (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    trace_id        VARCHAR(64)  NOT NULL,
    span_id         VARCHAR(32)  NOT NULL,
    parent_span_id  VARCHAR(32)  NULL,
    name            VARCHAR(128) NOT NULL,
    ts_start        DATETIME(3)  NOT NULL,
    ts_end          DATETIME(3)  NOT NULL,
    duration_ms     INT          NOT NULL,
    status          VARCHAR(16)  NOT NULL COMMENT 'ok|error|timeout',
    attributes_json JSON         NULL,
    error_message   TEXT         NULL,
    user_id         VARCHAR(64)  NULL,
    tenant_id       VARCHAR(64)  NULL,

    INDEX idx_trace   (trace_id),
    INDEX idx_span    (span_id),
    INDEX idx_name_ts (name, ts_start)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Phase 4: trace span 表 — 与 auth_audit_log 用户审计独立';