"""
Phase 3 audit log — loud-fail(ADR-005 §Audit Log 不 Silent-Fail)。

`write_audit_log(...)` DB 不可用或写入失败 → raise HTTPException(500),
绝不允许 pass / silent log。

用法:
    from CorpAI.platform.auth.audit import write_audit_log
    write_audit_log(user_id='alice', tenant_id='t1',
                    action='login', target='/admin/api/login',
                    ip='127.0.0.1', user_agent='Mozilla/5.0...',
                    result='allow')
"""
import logging

from fastapi import HTTPException

from CorpAI.platform.db import DatabasePool

logger = logging.getLogger(__name__)


def write_audit_log(
    user_id: str,
    tenant_id: str,
    action: str,
    target: str,
    ip: str,
    user_agent: str,
    result: str,
    reason: str | None = None,
) -> None:
    """loud-fail:DB 不可达 → HTTP 500(ADR-005)。"""
    conn = None
    try:
        conn = DatabasePool.get().get_conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO auth_audit_log
               (user_id, tenant_id, action, target, ip, user_agent, result, reason)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (user_id, tenant_id, action, target, ip, user_agent, result, reason),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.critical(f"audit log 写入失败: {e}")
        raise HTTPException(500, "审计日志不可用,请求拒绝")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


__all__ = ["write_audit_log"]
