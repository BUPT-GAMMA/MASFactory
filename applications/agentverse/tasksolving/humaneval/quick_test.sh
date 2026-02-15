#!/bin/bash
# HumanEval quick smoke test (MASFactory)

echo "=========================================="
echo "⚡ HumanEval quick test - MASFactory"
echo "=========================================="
echo ""

# Resolve script directory and repo root.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../../../.." && pwd )"

echo "Working directory: $(pwd)"
echo "Project root: $PROJECT_ROOT"
echo ""

# Check Python.
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: python3 not found"
    exit 1
fi

# Check dataset file (absolute path).
DATASET="$PROJECT_ROOT/applications/agentverse/assets/data/humaneval/test.jsonl"
if [ ! -f "$DATASET" ]; then
    echo "❌ Error: dataset file not found: $DATASET"
    echo "Make sure you are running from the correct repo checkout."
    exit 1
fi

# Check config file (absolute path).
CONFIG_FILE="$PROJECT_ROOT/applications/agentverse/assets/configs/humaneval-gpt4.yaml"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ Error: config file not found: $CONFIG_FILE"
    exit 1
fi

# Parameters.
CONFIG="${1:-humaneval-gpt4.yaml}"
MAX_SAMPLES="${2:-3}"
TASK_ID="${3:--1}"

echo "Configuration:"
echo "  Config: $CONFIG"

if [ "$TASK_ID" -ge 0 ] 2>/dev/null; then
    echo "  Task id: $TASK_ID (single task)"
else
    echo "  Samples: $MAX_SAMPLES"
fi

echo ""

# Run.
echo "Starting..."
echo ""

if [ "$TASK_ID" -ge 0 ] 2>/dev/null; then
    # Single task.
    python3 "$SCRIPT_DIR/test_humaneval.py" \
        --config "$CONFIG" \
        --task_file "humaneval/test.jsonl" \
        --task_id "$TASK_ID" \
        --debug
else
    # Multiple tasks.
    python3 "$SCRIPT_DIR/test_humaneval.py" \
        --config "$CONFIG" \
        --task_file "humaneval/test.jsonl" \
        --max_samples "$MAX_SAMPLES" \
        --debug
fi

EXIT_CODE=$?

echo ""
echo "=========================================="
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Done"
    echo ""
    echo "Results:"
    echo "  Latest output directory:"
    OUTPUT_DIR="$PROJECT_ROOT/applications/agentverse/assets/output/humaneval"
    LATEST_DIR=$(ls -td "$OUTPUT_DIR"/test_* 2>/dev/null | head -1)
    if [ -n "$LATEST_DIR" ]; then
        echo "    $LATEST_DIR"
        echo ""
        echo "  View the report:"
        echo "    cat $LATEST_DIR/evaluation_report.json | python3 -m json.tool"
    fi
else
    echo "❌ Failed (exit code: $EXIT_CODE)"
fi
echo "=========================================="
echo ""

exit $EXIT_CODE
