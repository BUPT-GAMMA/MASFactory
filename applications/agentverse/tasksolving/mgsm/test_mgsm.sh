#!/bin/bash

# Test script for MGSM (Multilingual Grade School Math) task

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if [ -x "${REPO_ROOT}/.venv/bin/python3" ]; then
    PYTHON_BIN="${REPO_ROOT}/.venv/bin/python3"
fi

echo "================================================================================"
echo "🧮 Testing MGSM (Multilingual Grade School Math) Task"
echo "================================================================================"
echo ""

# Source environment variables
if [ -f .env.sh ]; then
    source .env.sh
fi

# Test 1: Simple math problem
echo "📝 Test 1: Janet's duck eggs problem"
echo "--------------------------------------------------------------------------------"
timeout 180 "$PYTHON_BIN" "${SCRIPT_DIR}/run.py" \
    --task "Janet's ducks lay 16 eggs per day. She eats three for breakfast every morning and bakes muffins for her friends every day with four. She sells the remainder at the farmers' market daily for 2 dollars per fresh duck egg. How much in dollars does she make every day at the farmers' market?" \
    --model gpt-4o-mini \
    --max-turn 1 \
    --num-critics 1 \
    --max-inner-turns 1 \
    2>&1 | tail -20

echo ""
echo "✅ Test 1 completed"
echo ""

# Test 2: Cats and mice problem
echo "📝 Test 2: Cats and mice problem"
echo "--------------------------------------------------------------------------------"
timeout 180 "$PYTHON_BIN" "${SCRIPT_DIR}/run.py" \
    --task "If 5 cats can catch 5 mice in 5 minutes, how many cats are needed to catch 100 mice in 100 minutes?" \
    --model gpt-4o-mini \
    --max-turn 2 \
    --num-critics 2 \
    --max-inner-turns 2 \
    2>&1 | tail -20

echo ""
echo "✅ Test 2 completed"
echo ""

echo "================================================================================"
echo "🎉 All MGSM tests completed successfully!"
echo "================================================================================"
