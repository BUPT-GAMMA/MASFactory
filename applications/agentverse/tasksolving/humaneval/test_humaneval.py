#!/usr/bin/env python3
"""Batch runner and evaluator for HumanEval tasks.

Runs generation via the MASFactory HumanEval workflow and can optionally
evaluate an existing results file without re-running generation.
"""

import os
import sys
import json
import yaml
import re
import subprocess
import tempfile
import traceback
from datetime import datetime
from argparse import ArgumentParser
from pathlib import Path
from typing import Dict, List, Any

# Generation reads API settings from environment variables:
# - OPENAI_API_KEY
# - OPENAI_BASE_URL (or BASE_URL)
# Evaluation-only mode (`--skip_run`) does not require API credentials.

current_dir = os.path.dirname(os.path.abspath(__file__))
script_dir = Path(current_dir)
project_root = script_dir.parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from masfactory import Agent, Node
from applications.agentverse.tasksolving.humaneval.workflow import build_humaneval_graph
from applications.agentverse.utils import on_forward_after_hook

assets_dir = os.path.join(project_root, "applications", "agentverse", "assets")
config_dir = os.path.join(assets_dir, "configs")
data_dir = os.path.join(assets_dir, "data")
output_dir = os.path.join(assets_dir, "output", "humaneval")

parser = ArgumentParser(description="HumanEval batch runner (MASFactory)")
parser.add_argument("--config", type=str, default="humaneval-gpt4.yaml",
                    help="Config filename (under assets/configs/)")
parser.add_argument("--task_file", type=str, 
                    default="humaneval/test.jsonl",
                    help="Task file (under assets/data/)")
parser.add_argument("--output_path", type=str, default=None,
                    help="Output directory (default: assets/output/humaneval/<timestamp>)")
parser.add_argument("--task_id", type=int, default=-1,
                    help="Run a single task id (-1 runs all tasks)")
parser.add_argument("--max_samples", type=int, default=None,
                    help="Maximum samples (for quick smoke tests)")
parser.add_argument("--skip_run", action="store_true",
                    help="Skip generation; only evaluate existing results")
parser.add_argument("--results_file", type=str, default=None,
                    help="Results file to evaluate (use with --skip_run)")
parser.add_argument("--timeout", type=int, default=10,
                    help="Code execution timeout (seconds)")
parser.add_argument("--overwrite", action="store_true",
                    help="Overwrite existing results (default appends/resumes)")
parser.add_argument("--debug", action="store_true",
                    help="Enable debug output")

args = parser.parse_args()

if not args.skip_run and not os.getenv("OPENAI_API_KEY"):
    print("❌ Error: OPENAI_API_KEY environment variable not set")
    print("  Run: export OPENAI_API_KEY='your-api-key'")
    sys.exit(1)

def load_config(config_path: str) -> dict:
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_tasks(task_file: str) -> List[Dict]:
    tasks = []
    with open(task_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                tasks.append(json.loads(line))
    return tasks


def extract_python_code(response: str) -> str:
    """Extract Python code from a model response."""
    # Prefer Markdown code fences if present.
    code_blocks = re.findall(r'```python\n(.*?)```', response, re.DOTALL)
    if code_blocks:
        return code_blocks[-1].strip()
    
    code_blocks = re.findall(r'```\n(.*?)```', response, re.DOTALL)
    if code_blocks:
        return code_blocks[-1].strip()
    
    return response.strip()


def test_generated_code(code: str, test_code: str, task_id: str, timeout: int = 10) -> Dict[str, Any]:
    """Run the provided tests against the generated implementation."""
    result = {
        'passed': False,
        'error': None,
        'error_type': None
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        temp_file = f.name
        
        try:
            func_match = re.search(r'def\s+(\w+)\s*\(', code)
            if not func_match:
                result['error'] = "Cannot find function definition"
                result['error_type'] = "ParseError"
                return result
            
            func_name = func_match.group(1)
            
            full_code = f"{code}\n\n{test_code}\n\ncheck({func_name})"
            f.write(full_code)
            f.flush()
            
            process = subprocess.run(
                [sys.executable, temp_file],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            if process.returncode == 0:
                result['passed'] = True
            else:
                result['error'] = process.stderr
                # Best-effort error type classification.
                if 'AssertionError' in process.stderr:
                    result['error_type'] = 'AssertionError'
                elif 'SyntaxError' in process.stderr:
                    result['error_type'] = 'SyntaxError'
                elif 'IndentationError' in process.stderr:
                    result['error_type'] = 'IndentationError'
                elif 'NameError' in process.stderr:
                    result['error_type'] = 'NameError'
                elif 'TypeError' in process.stderr:
                    result['error_type'] = 'TypeError'
                elif 'AttributeError' in process.stderr:
                    result['error_type'] = 'AttributeError'
                else:
                    result['error_type'] = 'RuntimeError'
                    
        except subprocess.TimeoutExpired:
            result['error'] = f"Execution timeout (>{timeout}s)"
            result['error_type'] = 'TimeoutError'
        except Exception as e:
            result['error'] = str(e)
            result['error_type'] = type(e).__name__
        finally:
            try:
                os.unlink(temp_file)
            except:
                pass
    
    return result


def run_tasks():
    print("=" * 80)
    print("🚀 Starting HumanEval batch run")
    print("=" * 80)
    
    config_path = os.path.join(config_dir, args.config)
    if not os.path.exists(config_path):
        print(f"❌ Config file not found: {config_path}")
        sys.exit(1)
    
    config = load_config(config_path)
    print(f"✓ Loaded config: {config_path}")
    
    task_file = os.path.join(data_dir, args.task_file)
    if not os.path.exists(task_file):
        print(f"❌ Task file not found: {task_file}")
        sys.exit(1)
    
    tasks = load_tasks(task_file)
    print(f"✓ Loaded tasks: {len(tasks)}")
    
    if args.output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output_path = os.path.join(output_dir, f"test_{timestamp}")
    
    os.makedirs(args.output_path, exist_ok=True)
    print(f"✓ Output dir: {args.output_path}")
    
    results_file = os.path.join(args.output_path, "results.jsonl")
    skip_cnt = 0
    if not args.overwrite and os.path.exists(results_file):
        with open(results_file, "r") as f:
            for line in f:
                if line.strip():
                    skip_cnt += 1
        print(f"✓ Found {skip_cnt} existing results; resuming from task #{skip_cnt + 1}")
    
    if args.task_id >= 0:
        if args.task_id >= len(tasks):
            print(f"❌ task_id {args.task_id} out of range (total {len(tasks)} tasks)")
            sys.exit(1)
        task_list = [(args.task_id, tasks[args.task_id])]
        print(f"✓ Running single task: #{args.task_id}")
    else:
        max_samples = args.max_samples or len(tasks)
        task_list = list(enumerate(tasks[:max_samples]))
        if skip_cnt > 0:
            task_list = task_list[skip_cnt:]
        print(f"✓ Tasks to run: {len(task_list)}")
    
    print("=" * 80)
    print()
    
    result_file = open(results_file, "w" if args.overwrite else "a")
    
    total = len(task_list)
    processed = 0
    failed = 0
    
    try:
        for idx, (i, task) in enumerate(task_list):
            task_id = task.get("task_id", f"Task {i}")
            
            print("-" * 80)
            print(f"[{idx+1}/{total}] Processing task: {task_id}")
            print(f"Prompt: {task['prompt'][:80]}...")
            
            try:
                workflow = build_humaneval_graph(config)
                
                workflow.hook_register(
                    Node.Hook.FORWARD.AFTER, 
                    on_forward_after_hook,
                    recursion=True, 
                    target_type=Agent
                )
                
                task_description = task["prompt"]
                # RootGraph.invoke(input, attributes) expects task fields in `input` (messages),
                # not in `attributes`. See `RootGraph.invoke` implementation.
                result, attributes = workflow.invoke({"task_description": task_description}, {})

                if args.debug:
                    print(f"\n📝 result type: {type(result)}")
                    print(f"📝 attributes type: {type(attributes)}")
                    print(f"📝 attributes keys: {list(attributes.keys()) if hasattr(attributes, 'keys') else 'N/A'}")
                    print("\n🔍 DEBUG - full result:")
                    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
                    print("\n🔍 DEBUG - full attributes:")
                    print(json.dumps(attributes, indent=2, ensure_ascii=False, default=str))

                # Prefer solution from RootGraph output (edge_to_exit mapping) when available.
                solution = None
                if isinstance(result, dict):
                    solution = result.get("solution")
                if not solution and isinstance(attributes, dict):
                    solution = attributes.get("solution") or attributes.get("previous_plan")
                if not solution:
                    solution = "no solution yet."
                
                print(f"✅ Extracted solution length: {len(str(solution))} chars")
                if args.debug:
                    print(f"🔍 solution preview: {str(solution)[:200]}...")
                
                # Persist result.
                result_data = {
                    "task_id": task_id,
                    "index": i,
                    "prompt": task["prompt"],
                    "response": str(solution),
                    "test": task["test"],
                    "canonical_solution": task.get("canonical_solution", ""),
                }
                
                result_file.write(json.dumps(result_data, ensure_ascii=False) + "\n")
                result_file.flush()
                
                processed += 1
                print(f"✓ Task done ({processed}/{total})")
                
                # Cleanup workflow state.
                workflow.reset()
                
            except Exception as e:
                failed += 1
                print(f"✗ Task failed: {str(e)}")
                if args.debug:
                    print(traceback.format_exc())
                
                # Persist error info.
                result_data = {
                    "task_id": task_id,
                    "index": i,
                    "prompt": task["prompt"],
                    "response": None,
                    "test": task["test"],
                    "error": str(e),
                }
                result_file.write(json.dumps(result_data, ensure_ascii=False) + "\n")
                result_file.flush()
            
            print()
    
    finally:
        result_file.close()
    
    print("=" * 80)
    print("📊 Run completed")
    print(f"   Succeeded: {processed}/{total}")
    print(f"   Failed: {failed}/{total}")
    print(f"   Results saved to: {results_file}")
    print("=" * 80)
    print()


def evaluate_results():
    print("=" * 80)
    print("📊 Starting evaluation")
    print("=" * 80)
    print()
    
    # Pick results file.
    if args.skip_run and args.results_file:
        results_file = args.results_file
    else:
        results_file = os.path.join(args.output_path, "results.jsonl")
    
    if not os.path.exists(results_file):
        print(f"❌ Results file not found: {results_file}")
        return None
    
    # Counters.
    total = 0
    passed = 0
    failed = 0
    error_tasks = 0
    error_types = {}
    failed_tasks = []
    
    # Read and evaluate results.
    print("Evaluating results...\n")
    
    with open(results_file, "r") as f:
        for line in f:
            if not line.strip():
                continue
            
            data = json.loads(line)
            total += 1
            
            task_id = data.get('task_id', f"Task {total-1}")
            
            # Skip entries that already contain runtime errors.
            if "error" in data and data["error"]:
                error_tasks += 1
                print(f"⚠  {task_id}: runtime error - {data['error'][:50]}...")
                continue
            
            response = data.get("response", "")
            if not response:
                error_tasks += 1
                print(f"⚠  {task_id}: empty response")
                continue
            
            code = extract_python_code(response)
            test_code = data.get("test", "")
            
            # Run local tests.
            test_result = test_generated_code(code, test_code, task_id, timeout=args.timeout)
            
            if test_result['passed']:
                passed += 1
                print(f"✓ {task_id}: passed")
            else:
                failed += 1
                error_type = test_result['error_type'] or 'Unknown'
                error_types[error_type] = error_types.get(error_type, 0) + 1
                failed_tasks.append({
                    'task_id': task_id,
                    'error_type': error_type,
                    'error': test_result['error'][:200] if test_result['error'] else None
                })
                print(f"✗ {task_id}: failed ({error_type})")
    
    print()
    
    # Summary stats.
    valid_total = passed + failed
    pass_rate = (passed / valid_total * 100) if valid_total > 0 else 0
    
    # Report payload.
    report = {
        "timestamp": datetime.now().isoformat(),
        "config": args.config,
        "task_file": args.task_file,
        "total_lines": total,
        "valid_tests": valid_total,
        "passed": passed,
        "failed": failed,
        "error_tasks": error_tasks,
        "pass_rate": round(pass_rate, 2),
        "error_types": error_types,
        "failed_tasks": failed_tasks[:20],  # Keep only the first 20 failures.
    }
    
    # Write report.
    report_dir = os.path.dirname(results_file)
    report_file = os.path.join(report_dir, "evaluation_report.json")
    
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    # Print report.
    print("=" * 80)
    print("📊 Test report")
    print("=" * 80)
    print(f"Total tasks: {total}")
    print(f"Valid tests: {valid_total}")
    print(f"  ✓ Passed: {passed} ({pass_rate:.2f}%)")
    print(f"  ✗ Failed: {failed}")
    print("Errors:")
    print(f"  ⚠  Runtime errors: {error_tasks}")
    print()
    
    if error_types:
        print("Error type breakdown:")
        for error_type, count in sorted(error_types.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / failed * 100) if failed > 0 else 0
            print(f"  {error_type:20s}: {count:3d} ({percentage:.1f}%)")
        print()
    
    print("=" * 80)
    print(f"📄 Detailed report saved to: {report_file}")
    print("=" * 80)
    print()
    
    return report


def main():
    try:
        # Run generation.
        if not args.skip_run:
            run_tasks()
        
        # Evaluate results.
        report = evaluate_results()
        
        # Exit code.
        if report and report['pass_rate'] > 0:
            sys.exit(0)
        else:
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n⚠  User interrupted")
        sys.exit(130)
    except Exception as e:
        print(f"❌ Execution failed: {str(e)}")
        if args.debug:
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
