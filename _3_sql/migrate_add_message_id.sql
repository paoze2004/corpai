-- ============================================================
-- v3.3: sre_action_plans 加 message_id 列
-- 关联:飞书卡片 UI 替换需要 message_id — 审批后 PATCH /im/v1/messages/{message_id}
-- ============================================================

ALTER TABLE sre_action_plans
    ADD COLUMN message_id VARCHAR(64) NOT NULL DEFAULT '' COMMENT '飞书消息 ID,审批后 PATCH 替换卡片';

-- 索引(按 message_id 查 plan 用于批量清理孤儿消息)
ALTER TABLE sre_action_plans
    ADD INDEX idx_message_id (message_id);