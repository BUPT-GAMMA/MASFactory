#!/bin/bash
# HumanEval batch runner (MASFactory)

echo "========================================"
echo "🚀 HumanEval batch run - MASFactory"
echo "========================================"
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
DATA_FILE="$PROJECT_ROOT/applications/agentverse/assets/data/humaneval/test.jsonl"
if [ ! -f "$DATA_FILE" ]; then
    echo "❌ Error: dataset file not found"
    echo "Expected path: $DATA_FILE"
    exit 1
fi

# Check config file (absolute path).
CONFIG_FILE="$PROJECT_ROOT/applications/agentverse/assets/configs/humaneval-gpt4.yaml"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ Error: config file not found"
    echo "Expected path: $CONFIG_FILE"
    exit 1
fi

# Default parameters.
SAMPLES=${1:-5}
CONFIG=${2:-humaneval-gpt4.yaml}
TASK_ID=${3:--1}

echo "Test configuration:"
echo "  Config: $CONFIG"

# Run the full dataset if requested.
if [ "$SAMPLES" = "all" ] || [ "$SAMPLES" = "ALL" ]; then
    echo "  Samples: all (164)"
    echo "  Task id: $TASK_ID"
    echo ""
    echo "⚠️  Note: a full run can take a long time"
    echo ""
    echo "Starting..."
    echo ""
    
    # Full run (no --max_samples).
    python3 "$SCRIPT_DIR/test_humaneval.py" \
        --config "$CONFIG" \
        --task_file "humaneval/test.jsonl" \
        --task_id "$TASK_ID" \
        --debug
else
    if [ "$SAMPLES" -ge 0 ] 2>/dev/null; then
        echo "  Samples: $SAMPLES"
        echo "  Task id: $TASK_ID"
        echo ""
        echo "Starting..."
        echo ""
        
        if [ "$TASK_ID" -ge 0 ] 2>/dev/null; then
            # Run a single task.
            python3 "$SCRIPT_DIR/test_humaneval.py" \
                --config "$CONFIG" \
                --task_file "humaneval/test.jsonl" \
                --task_id "$TASK_ID" \
                --debug
        else
            # Run the first N tasks.
            python3 "$SCRIPT_DIR/test_humaneval.py" \
                --config "$CONFIG" \
                --task_file "humaneval/test.jsonl" \
                --max_samples "$SAMPLES" \
                --debug
        fi
    else
        echo "❌ Error: invalid samples argument: $SAMPLES"
        echo ""
        echo "Usage:"
        echo "  ./run_test.sh [samples] [config] [task_id]"
        echo ""
        echo "Examples:"
        echo "  ./run_test.sh 5                              # Run first 5 tasks"
        echo "  ./run_test.sh all                            # Run all tasks"
        echo "  ./run_test.sh 10 humaneval-gpt4.yaml         # Use a specific config"
        echo "  ./run_test.sh 1 humaneval-gpt4.yaml 0        # Run a single task (id=0)"
        exit 1
    fi
fi

EXIT_CODE=$?

echo ""
echo "========================================"
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Done"
    echo ""
    echo "Results:"
    echo "  Find the latest output directory:"
    echo "    ls -lt $PROJECT_ROOT/applications/agentverse/assets/output/humaneval/"
    echo ""
    echo "  View the report:"
    echo "    cat $PROJECT_ROOT/applications/agentverse/assets/output/humaneval/test_*/evaluation_report.json | python3 -m json.tool"
else
    echo "❌ Failed (exit code: $EXIT_CODE)"
fi
echo "========================================"

exit $EXIT_CODE
