-- ============================================================
-- _0_CorpAI 全量建表脚本
-- 合并所有业务表的 CREATE TABLE 语句
-- 数据库: _0_CorpAI
-- ============================================================

-- 数据库 _0_CorpAI 必须已存在(用户在 MySQL 手动 CREATE DATABASE _0_CorpAI)。
-- 本脚本只 CREATE TABLE IF NOT EXISTS,不 DROP DATABASE — 避免误删数据。
-- 运行:mysql -u admin -p _0_CorpAI < _3_sql/create_all_tables._3_sql
--     (注意用 -D _0_CorpAI 选库,而不是依赖脚本 USE)


-- ==================== 用户偏好表 ====================
CREATE TABLE IF NOT EXISTS user_profiles (
    profile_key VARCHAR(50) NOT NULL COMMENT '偏好键名',
    profile_value VARCHAR(200) NOT NULL COMMENT '偏好值',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (profile_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户偏好';

-- ==================== 查询历史表 ====================
CREATE TABLE IF NOT EXISTS query_history (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    intent_type VARCHAR(30) NOT NULL COMMENT '意图类型：weather/flight/train等',
    query_content TEXT NOT NULL COMMENT '查询内容JSON',
    query_time DATETIME NOT NULL COMMENT '查询时间',
    INDEX idx_time (query_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='查询历史';

-- ==================== 短期对话表 ====================
CREATE TABLE IF NOT EXISTS short_term_messages (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    role VARCHAR(10) NOT NULL COMMENT '消息角色：user 或 assistant',
    content TEXT NOT NULL COMMENT '消息内容',
    message_time VARCHAR(10) NOT NULL COMMENT '时间戳 HH:MM:SS',
    message_order INT NOT NULL COMMENT '消息顺序号',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='短期对话';
