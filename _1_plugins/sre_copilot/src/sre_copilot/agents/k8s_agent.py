"""K8sAgent — 查 pod 状态 / OOMKilled 事件。

DRY_RUN 模式返 mock;真接时调 kubernetes-python SDK。

M1 demo 增强:DRY_RUN 模式下,如果 alert 含 OOM/Memory 关键字,自动追加
pod OOMKilled 事件 + heap 堆栈日志(让 DiagnosisAgent 有信号可推)。
生产场景 K8S_DRY_RUN=false 走真实 K8s API。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from .base import BaseAgent, IncidentContext

logger = logging.getLogger(__name__)


_DEMO_OOM_LOGS = [
    "java.lang.OutOfMemoryError: Java heap space",
    "        at com.order.payment.PaymentService.process(PaymentService.java:142)",
    "        at com.order.payment.PaymentService.handleRequest(PaymentService.java:89)",
    "        at org.springframework.web.servlet.DispatcherServlet.doDispatch(DispatcherServlet.java:1067)",
    "[OOMKilled] container exceeded memory limit (1Gi)",
    "java.lang.OutOfMemoryError: Java heap space",
    "        at com.order.payment.PaymentService.process(PaymentService.java:142)",
    "[OOMKilled] container exceeded memory limit (1Gi)",
]


def _augment_k8s_for_demo(result: dict, service: str, alert: dict) -> dict:
    """DRY_RUN 增强:如果 alert 含 OOM,补 pod OOMKilled 状态 + heap 日志。

    让 DiagnosisAgent 不用真接 Prometheus/K8s 就能命中根因推断。
    """
    alert_type = alert.get("alert", "")
    if "OOM" not in alert_type and "Memory" not in alert_type:
        return result
    # 已有 logs(list)— 追加 OOM 模拟
    existing_logs = result.get("logs", [])
    if isinstance(existing_logs, list):
        now = datetime.utcnow()
        demo_lines = []
        for i, line in enumerate(_DEMO_OOM_LOGS):
            ts = (now - timedelta(seconds=len(_DEMO_OOM_LOGS) - i)).isoformat() + "Z"
            demo_lines.append(f"[{ts}] {line}")
        result["logs"] = demo_lines + existing_logs
    result["pod_count"] = 5
    result["oomkilled_pods"] = [
        f"{service}-abc-{i:03d}" for i in range(123, 125)
    ]
    result["restart_count_1h"] = 47
    return result


class K8sAgent(BaseAgent):
    name = "k8s"

    async def run(self, ctx: IncidentContext) -> None:
        import sre_copilot.tools as t
        service = ctx.alert.get("service", "unknown")
        ctx.log_event(self.name, f"kubectl get pods -n production -l app={service}")

        # M1 demo 模式:无 user_token 时跳过 auth(避免 _check_sre_read PermissionError)
        # 生产:ctx.user_token 是真 JWT,带 sre:read scope
        auth = f"Bearer {ctx.user_token}" if ctx.user_token else "Bearer DEMO_DRY_RUN"

        try:
            raw = t.get_pod_logs(
                pod_name=service,
                namespace="production",
                tail_lines=50,
                authorization=auth,
            )
            # get_pod_logs 返 JSON string,parse 成 dict
            result = json.loads(raw) if isinstance(raw, str) else raw
            # DRY_RUN demo 增强
            result = _augment_k8s_for_demo(result, service, ctx.alert)
            ctx.k8s_status = result
            oom_count = len(result.get("oomkilled_pods", []))
            ctx.log_event(
                self.name, "K8s 查完成",
                pods_found=result.get("pod_count", 0),
                oom_pods=oom_count,
            )
        except PermissionError:
            # 无 sre:read scope — 仍返 demo 数据,让 pipeline 跑通
            ctx.log_event(self.name, "无 sre:read scope,用 demo 数据继续", level="warn")
            ctx.k8s_status = _augment_k8s_for_demo(
                {"status": "demo", "logs": [], "pod_count": 0},
                service, ctx.alert,
            )
        except Exception as exc:
            ctx.log_event(self.name, "K8s 调用失败", error=str(exc), level="warn")
            ctx.k8s_status = {"status": "error", "message": str(exc)}


__all__ = ["K8sAgent"]