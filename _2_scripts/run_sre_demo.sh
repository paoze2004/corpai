#!/bin/bash
# _2_scripts/run_sre_demo.sh — M6.5 一键起 SRE Incident 完整 Kafka 链路
#
# 启 4 个进程:
#   1. Kafka(已假设 corpai-kafka.yml 跑起来)
#   2. SRE Pipeline consumer(订阅 5 topic,跑 workflow)
#   3. Action Executor consumer(订阅 sre.actions,跑 action,发 sre.audit)
#   4. Mock Producer CLI(推 1 个 OOM incident 到 Kafka)
#
# 用法:
#   bash _2_scripts/run_sre_demo.sh
#
# 前置:
#   - docker compose -f corpai-kafka.yml up -d
#   - uv sync --group dev
#   - _1_plugins 都已 editable install

set -e

KAFKA_BOOTSTRAP="${KAFKA_BOOTSTRAP:-localhost:9092}"

echo "=========================================="
echo "CorpAI SRE Incident Demo (M6)"
echo "Kafka: $KAFKA_BOOTSTRAP"
echo "=========================================="

# 检查 Kafka 是不是活的
if ! docker exec corpai-kafka kafka-broker-api-versions.sh --bootstrap-server "$KAFKA_BOOTSTRAP" >/dev/null 2>&1; then
    echo "❌ Kafka 不可达 ($KAFKA_BOOTSTRAP)"
    echo "   跑: docker compose -f corpai-kafka.yml up -d"
    exit 1
fi

# 后台启 SRE Pipeline consumer
echo "▶ 启 SRE Pipeline consumer(后台)..."
uv run python -c "
import asyncio
from sre_copilot.kafka_pipeline import SREPipelineConsumer
from sre_copilot.workflow import IncidentWorkflow

async def main():
    c = SREPipelineConsumer(
        bootstrap_servers='$KAFKA_BOOTSTRAP',
        workflow=IncidentWorkflow(),
    )
    await c.start()
    try:
        # 永久跑
        while True:
            await asyncio.sleep(1)
    finally:
        await c.stop()

asyncio.run(main())
" > /tmp/sre-pipeline.log 2>&1 &
PIPELINE_PID=$!
echo "  Pipeline PID=$PIPELINE_PID,日志 /tmp/sre-pipeline.log"

sleep 1

# 后台启 Action Executor consumer
echo "▶ 启 Action Executor consumer(后台)..."
uv run python -c "
import asyncio
from sre_copilot.kafka_executor import ActionExecutorKafka

async def main():
    e = ActionExecutorKafka(bootstrap_servers='$KAFKA_BOOTSTRAP')
    await e.start()
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await e.stop()

asyncio.run(main())
" > /tmp/sre-executor.log 2>&1 &
EXECUTOR_PID=$!
echo "  Executor PID=$EXECUTOR_PID,日志 /tmp/sre-executor.log"

sleep 2

# 推 1 个 OOM incident
echo ""
echo "▶ 推 1 个 OOM incident 到 Kafka..."
uv run python scripts/sre_mock_producer.py \
    --scenario oom \
    --count 1 \
    --bootstrap-servers "$KAFKA_BOOTSTRAP"

sleep 3

echo ""
echo "▶ 验证消息到 5 topic 了没:"
for topic in sre.alerts sre.metrics sre.k8s sre.logs sre.historical sre.actions sre.audit; do
    count=$(docker exec corpai-kafka kafka-run-class.sh kafka.tools.GetOffsetShell \
        --bootstrap-server "$KAFKA_BOOTSTRAP" \
        --topic "$topic" 2>/dev/null | tail -1 | awk -F: '{print $3}')
    printf "  %-20s offset=%s\n" "$topic" "${count:-0}"
done

echo ""
echo "▶ Pipeline 日志(后 10 行):"
tail -10 /tmp/sre-pipeline.log 2>/dev/null || echo "  (无日志)"

echo ""
echo "▶ Executor 日志(后 10 行):"
tail -10 /tmp/sre-executor.log 2>/dev/null || echo "  (无日志)"

# 清理
echo ""
echo "▶ 关掉后台 consumer..."
kill $PIPELINE_PID 2>/dev/null || true
kill $EXECUTOR_PID 2>/dev/null || true
sleep 1

echo ""
echo "✅ Demo 完成。Kafka topic 留着,看 /tmp/sre-*.log 看细节。"