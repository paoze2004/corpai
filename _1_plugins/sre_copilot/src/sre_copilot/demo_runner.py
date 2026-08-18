"""SRE Incident Demo Runner — M5.1。

异步跑 incident 流水线,所有事件存 in-memory,供 SSE 订阅。

设计:
- 一个 DemoRunner 单例(模块级),run_id → asyncio.Queue
- start(alert) → 启 background task,跑 workflow,每步把 ctx 快照推到 queue
- stream(run_id) async generator → yield 事件流
- get_status(run_id) → 当前 ctx(action_plan / verification 状态)

替代直接暴露 workflow.run()(后者 yield 是 coroutine,需要个 manager 包装给 SSE)。
"""
from __future__ import annotations

import asyncio
import copy
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sre_copilot.workflow import IncidentWorkflow


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class DemoRunner:
    """Demo 流水线 runner — 内存存储 + 事件流。"""

    def __init__(self):
        self._runs: dict[str, dict] = {}  # run_id → {status, events, ctx_snapshot, queue}
        self._workflow = IncidentWorkflow()
        self._tasks: dict[str, asyncio.Task] = {}

    def _serialize(self, ctx) -> dict:
        """把 ctx 转 dict(JSON-friendly),SSE 输出用。"""
        return {
            "events": list(ctx.events),
            "alert": ctx.alert,
            "metrics": ctx.metrics,
            "k8s_status": ctx.k8s_status,
            "log_samples": ctx.log_samples,
            "historical_incidents": ctx.historical_incidents,
            "diagnosis": ctx.diagnosis,
            "action_plan": ctx.action_plan,
            "verification": getattr(ctx, "verification", None),
        }

    async def start(self, alert: dict, run_id: str | None = None) -> str:
        """启一个 demo run,返回 run_id。"""
        rid = run_id or f"demo-{uuid.uuid4().hex[:8]}"
        queue: asyncio.Queue = asyncio.Queue()
        self._runs[rid] = {
            "status": "running",
            "alert": alert,
            "started_at": _now(),
            "events": [],
            "ctx_snapshot": {},
            "queue": queue,
        }
        self._tasks[rid] = asyncio.create_task(self._run_pipeline(rid, alert, queue))
        return rid

    async def _run_pipeline(self, run_id: str, alert: dict, queue: asyncio.Queue) -> None:
        """background task — 跑 workflow,每步 push 事件。"""
        try:
            final_ctx = None
            async for ctx in self._workflow.run(alert=alert, run_id=run_id, user_token=None):
                snap = self._serialize(ctx)
                self._runs[run_id]["ctx_snapshot"] = snap
                self._runs[run_id]["events"] = snap["events"]
                # 每个 ctx 推一个事件
                await queue.put({
                    "type": "step",
                    "ts": _now(),
                    "run_id": run_id,
                    "data": snap,
                })
                final_ctx = ctx
            # 完成事件
            self._runs[run_id]["status"] = "completed"
            await queue.put({
                "type": "completed",
                "ts": _now(),
                "run_id": run_id,
                "final": self._serialize(final_ctx) if final_ctx else None,
            })
        except Exception as exc:
            self._runs[run_id]["status"] = "failed"
            await queue.put({
                "type": "failed",
                "ts": _now(),
                "run_id": run_id,
                "error": str(exc),
            })

    async def stream(self, run_id: str):
        """SSE generator — 订阅 run_id 的事件流。"""
        run = self._runs.get(run_id)
        if not run:
            yield {"type": "error", "error": f"run_id {run_id} not found"}
            return
        queue: asyncio.Queue = run["queue"]
        # 推初始状态
        yield {
            "type": "init",
            "ts": _now(),
            "run_id": run_id,
            "status": run["status"],
            "alert": run["alert"],
            "started_at": run["started_at"],
        }
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=120)
                yield event
                if event["type"] in ("completed", "failed"):
                    break
            except asyncio.TimeoutError:
                yield {"type": "heartbeat", "ts": _now(), "run_id": run_id}
                if run["status"] in ("completed", "failed"):
                    break

    def get_status(self, run_id: str) -> dict | None:
        """返当前 run 状态(M5 admin 页面轮询用)。"""
        run = self._runs.get(run_id)
        if not run:
            return None
        return {
            "run_id": run_id,
            "status": run["status"],
            "started_at": run["started_at"],
            "events_count": len(run["events"]),
            "has_action_plan": bool(run["ctx_snapshot"].get("action_plan")),
            "has_verification": bool(run["ctx_snapshot"].get("verification")),
        }

    def list_runs(self) -> list[dict]:
        """admin 页面用:列出所有 demo run。"""
        return [
            {"run_id": rid, "status": r["status"], "started_at": r["started_at"]}
            for rid, r in self._runs.items()
        ]


# 模块级单例
_runner: DemoRunner | None = None


def get_demo_runner() -> DemoRunner:
    global _runner
    if _runner is None:
        _runner = DemoRunner()
    return _runner


__all__ = ["DemoRunner", "get_demo_runner"]