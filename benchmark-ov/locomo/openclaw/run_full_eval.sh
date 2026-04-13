#!/bin/bash

set -e

: '
OpenClaw 完整评估流程脚本

用法:
  ./run_full_eval.sh                      # 只导入 OpenViking (所有 samples)
  ./run_full_eval.sh --with-claw-import   # 同时导入 OpenViking 和 OpenClaw (所有 samples)
  ./run_full_eval.sh --skip-import        # 跳过导入步骤 (所有 samples)
  ./run_full_eval.sh --sample 0           # 只处理第 0 个 sample
  ./run_full_eval.sh --sample 1 --with-claw-import  # 只处理第 1 个 sample，同时导入 OpenClaw
  ./run_full_eval.sh --force-ingest       # 强制重新导入所有数据
'

# 基于脚本所在目录计算数据文件路径
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INPUT_FILE="$SCRIPT_DIR/../data/locomo10.json"
RESULT_DIR="$SCRIPT_DIR/result"
OUTPUT_CSV="$RESULT_DIR/qa_results.csv"
GATEWAY_TOKEN="${GATEWAY_TOKEN:-}"
GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:19789}"
OV_URL="${OV_URL:-http://127.0.0.1:2934}"

# 测试环境 OpenClaw 状态目录（覆盖系统级 OPENCLAW_HOME）
REPO_ROOT="$(cd "$SCRIPT_DIR" && cd ../../../.. && pwd)"
export OPENCLAW_HOME="$REPO_ROOT/config/.openclaw"
export OPENCLAW_STATE_DIR="$REPO_ROOT/config/.openclaw"

# Judge API 配置（volcengine coding endpoint）
JUDGE_BASE_URL="${JUDGE_BASE_URL:-https://ark.cn-beijing.volces.com/api/coding/v3}"
JUDGE_TOKEN="${JUDGE_TOKEN:-}"
JUDGE_MODEL="${JUDGE_MODEL:-doubao-seed-2-0-code-preview-260215}"

# Python：优先使用 OV venv
OV_VENV_PYTHON="$(cd "$SCRIPT_DIR" && cd ../../../.. && pwd)/openviking-runtime/venv/Scripts/python.exe"
if [ -x "$OV_VENV_PYTHON" ]; then
    PYTHON="$OV_VENV_PYTHON"
else
    PYTHON="python"
fi


# 解析参数
SKIP_IMPORT=false
WITH_CLAW_IMPORT=false
FORCE_INGEST=false
SAMPLE_IDX=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-import)
            SKIP_IMPORT=true
            shift
            ;;
        --with-claw-import)
            WITH_CLAW_IMPORT=true
            shift
            ;;
        --force-ingest)
            FORCE_INGEST=true
            shift
            ;;
        --sample)
            if [ -z "$2" ] || [[ "$2" == --* ]]; then
                echo "错误: --sample 需要一个参数 (sample index, 0-based)"
                exit 1
            fi
            SAMPLE_IDX="$2"
            shift 2
            ;;
        *)
            echo "警告: 未知参数 $1"
            shift
            ;;
    esac
done

# 构建 sample 参数
SAMPLE_ARG=""
if [ -n "$SAMPLE_IDX" ]; then
    SAMPLE_ARG="--sample $SAMPLE_IDX"
    # 如果指定了 sample，修改输出文件名以避免覆盖
    OUTPUT_CSV="$RESULT_DIR/qa_results_sample${SAMPLE_IDX}.csv"
fi

# 构建 force-ingest 参数
FORCE_INGEST_ARG=""
if [ "$FORCE_INGEST" = true ]; then
    FORCE_INGEST_ARG="--force-ingest"
fi

# 确保结果目录存在
mkdir -p "$RESULT_DIR"

# Step 1: 导入数据
if [ "$SKIP_IMPORT" = false ]; then
    if [ "$WITH_CLAW_IMPORT" = true ]; then
        echo "[1/5] 导入数据到 OpenViking 和 OpenClaw..."

        # 后台运行 OpenViking 导入
        "$PYTHON" "$SCRIPT_DIR/import_to_ov.py" --no-user-agent-id --input "$INPUT_FILE" --openviking-url "$OV_URL" $FORCE_INGEST_ARG $SAMPLE_ARG > "$RESULT_DIR/import_ov.log" 2>&1 &
        PID_OV=$!

        # 后台运行 OpenClaw 导入
        "$PYTHON" "$SCRIPT_DIR/eval.py" ingest "$INPUT_FILE" $FORCE_INGEST_ARG --token "$GATEWAY_TOKEN" --base-url "$GATEWAY_URL" $SAMPLE_ARG > "$RESULT_DIR/import_claw.log" 2>&1 &
        PID_CLAW=$!

        # 等待两个导入任务完成
        wait $PID_OV $PID_CLAW
    else
        echo "[1/5] 导入数据到 OpenViking..."
        "$PYTHON" "$SCRIPT_DIR/import_to_ov.py" --no-user-agent-id --input "$INPUT_FILE" --openviking-url "$OV_URL" $FORCE_INGEST_ARG $SAMPLE_ARG
    fi

    echo "导入完成，等待 1 分钟..."
    sleep 60
else
    echo "[1/5] 跳过导入数据..."
fi

# Step 2: 运行 QA 模型（默认输出到 result/qa_results.csv）
echo "[2/5] 运行 QA 评估..."
"$PYTHON" "$SCRIPT_DIR/eval.py" qa "$INPUT_FILE" --token "$GATEWAY_TOKEN" --base-url "$GATEWAY_URL" $SAMPLE_ARG --parallel 3 --output "${OUTPUT_CSV%.csv}"

# Step 3: 裁判打分
echo "[3/5] 裁判打分..."
"$PYTHON" "$SCRIPT_DIR/judge.py" --input "$OUTPUT_CSV" --parallel 5 \
  --base-url "$JUDGE_BASE_URL" --token "$JUDGE_TOKEN" --model "$JUDGE_MODEL"

# Step 4: 计算结果
echo "[4/5] 计算结果..."
"$PYTHON" "$SCRIPT_DIR/stat_judge_result.py" --input "$OUTPUT_CSV"

echo "[5/5] 完成!"
echo "结果文件: $OUTPUT_CSV"
