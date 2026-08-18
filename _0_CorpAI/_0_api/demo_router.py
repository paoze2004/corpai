"""Demo API Router — M5.2 HTTP endpoints。

- POST /demo/trigger 启一个 incident 流水线
- GET  /demo/stream/{run_id}  SSE 实时事件
- GET  /demo/status/{run_id}  当前状态
- GET  /demo/runs            列出所有 run

不进 _0_CorpAI/api/app.py(避免该文件继续膨胀),独立 router 挂上 app。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from sre_copilot.demo_runner import get_demo_runner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/trigger")
async def trigger_incident(alert: dict) -> dict:
    """启一个 demo incident run。

    Body 例:{"alert": "OOMKilled", "service": "order-api", "severity": "P2"}
    """
    if not isinstance(alert, dict):
        raise HTTPException(400, "alert 必须是 dict")
    if "alert" not in alert:
        raise HTTPException(400, "alert 字段必填")
    runner = get_demo_runner()
    run_id = await runner.start(alert)
    return {"run_id": run_id, "status": "running"}


@router.get("/stream/{run_id}")
async def stream_incident(run_id: str):
    """SSE:实时事件流。"""
    runner = get_demo_runner()
    async def event_gen():
        async for ev in runner.stream(run_id):
            yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.get("/status/{run_id}")
async def get_run_status(run_id: str) -> dict:
    """返 run 当前状态(给 admin 页面轮询用,SSE 失败时 fallback)。"""
    runner = get_demo_runner()
    status = runner.get_status(run_id)
    if not status:
        raise HTTPException(404, f"run_id {run_id} not found")
    return status


@router.get("/runs")
async def list_runs() -> list[dict]:
    """admin 页面:列出所有 demo run。"""
    return get_demo_runner().list_runs()


__all__ = ["router"]