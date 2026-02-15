#!/usr/bin/env python3
"""Offline evaluator for HumanEval results.

Evaluates an existing `results.jsonl` file by running the provided tests locally.
"""

import os
import sys
import json
import re
import subprocess
import tempfile
from datetime import datetime
from argparse import ArgumentParser
from typing import Dict, Any
from collections import Counter

# Offline evaluator: no API credentials required.
parser = ArgumentParser(description="HumanEval results evaluator (offline)")
parser.add_argument("--results_file", type=str, required=True,
                    help="Path to results file (results.jsonl)")
parser.add_argument("--output_file", type=str, default=None,
                    help="Output report path (default: same directory as results_file)")
parser.add_argument("--timeout", type=int, default=10,
                    help="Code execution timeout (seconds)")
parser.add_argument("--verbose", action="store_true",
                    help="Show verbose progress output")
parser.add_argument("--show_errors", action="store_true",
                    help="Show detailed error messages")

args = parser.parse_args()


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
    """Run the provided test code against the generated implementation."""
    result = {
        'passed': False,
        'error': None,
        'error_type': None,
        'stdout': None,
        'stderr': None
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        temp_file = f.name
        
        try:
            # Extract function name.
            func_match = re.search(r'def\s+(\w+)\s*\(', code)
            if not func_match:
                result['error'] = "Cannot find function definition in code"
                result['error_type'] = "ParseError"
                return result
            
            func_name = func_match.group(1)
            
            # Execute `code + test_code` with the standard HumanEval check() entry.
            full_code = f"{code}\n\n{test_code}\n\ncheck({func_name})"
            f.write(full_code)
            f.flush()
            
            process = subprocess.run(
                [sys.executable, temp_file],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            result['stdout'] = process.stdout
            result['stderr'] = process.stderr
            
            if process.returncode == 0:
                result['passed'] = True
            else:
                result['error'] = process.stderr
                # Best-effort error type classification.
                stderr = process.stderr
                if 'AssertionError' in stderr:
                    result['error_type'] = 'AssertionError'
                elif 'SyntaxError' in stderr:
                    result['error_type'] = 'SyntaxError'
                elif 'IndentationError' in stderr:
                    result['error_type'] = 'IndentationError'
                elif 'NameError' in stderr:
                    result['error_type'] = 'NameError'
                elif 'TypeError' in stderr:
                    result['error_type'] = 'TypeError'
                elif 'AttributeError' in stderr:
                    result['error_type'] = 'AttributeError'
                elif 'ImportError' in stderr or 'ModuleNotFoundError' in stderr:
                    result['error_type'] = 'ImportError'
                elif 'ValueError' in stderr:
                    result['error_type'] = 'ValueError'
                elif 'IndexError' in stderr:
                    result['error_type'] = 'IndexError'
                elif 'KeyError' in stderr:
                    result['error_type'] = 'KeyError'
                elif 'RecursionError' in stderr:
                    result['error_type'] = 'RecursionError'
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


def evaluate_results():
    """Evaluate all tasks in the provided results file."""
    
    print("=" * 80)
    print("📊 HumanEval results evaluation (MASFactory)")
    print("=" * 80)
    print(f"Results file: {args.results_file}")
    print()
    
    if not os.path.exists(args.results_file):
        print(f"❌ Results file not found: {args.results_file}")
        sys.exit(1)
    
    # Counters.
    total = 0
    passed = 0
    failed = 0
    parse_error = 0
    no_response = 0
    run_error = 0
    
    error_types = Counter()
    failed_tasks = []
    passed_tasks = []
    
    # Read and evaluate results.
    print("Evaluating...\n")
    
    with open(args.results_file, "r") as f:
        for line_num, line in enumerate(f, 1):
            if not line.strip():
                continue
            
            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"⚠  Warning: JSON parse failed at line {line_num}: {e}")
                continue
            
            total += 1
            task_id = data.get('task_id', f'Task {total-1}')
            
            # Skip entries that already contain runtime errors.
            if "error" in data and data["error"]:
                run_error += 1
                if args.verbose:
                    print(f"⚠  {task_id}: runtime error - {data['error']}")
                continue
            
            # Extract code from the model response.
            response = data.get("response", "")
            if not response:
                no_response += 1
                if args.verbose:
                    print(f"⚠  {task_id}: empty response")
                continue
            
            code = extract_python_code(response)
            if not code or 'def ' not in code:
                parse_error += 1
                if args.verbose:
                    print(f"⚠  {task_id}: cannot parse code")
                continue
            
            test_code = data.get("test", "")
            if not test_code:
                if args.verbose:
                    print(f"⚠  {task_id}: missing test code")
                continue
            
            # Run local tests.
            test_result = test_generated_code(code, test_code, task_id, timeout=args.timeout)
            
            if test_result['passed']:
                passed += 1
                passed_tasks.append(task_id)
                if args.verbose:
                    print(f"✓ {task_id}: passed")
            else:
                failed += 1
                error_type = test_result['error_type'] or 'Unknown'
                error_types[error_type] += 1
                
                failed_info = {
                    'task_id': task_id,
                    'error_type': error_type,
                    'error': test_result['error'],
                    'code': code[:200] + '...' if len(code) > 200 else code
                }
                failed_tasks.append(failed_info)
                
                if args.verbose or args.show_errors:
                    print(f"✗ {task_id}: failed ({error_type})")
                    if args.show_errors and test_result['error']:
                        print(f"  Error: {test_result['error'][:200]}")
                        print()
    
    # Summary stats.
    valid_total = passed + failed
    pass_rate = (passed / valid_total * 100) if valid_total > 0 else 0
    
    # Report payload.
    report = {
        "timestamp": datetime.now().isoformat(),
        "results_file": args.results_file,
        "total_lines": total,
        "valid_tests": valid_total,
        "passed": passed,
        "failed": failed,
        "run_error": run_error,
        "no_response": no_response,
        "parse_error": parse_error,
        "pass_rate": round(pass_rate, 2),
        "error_types": dict(error_types),
        "passed_tasks": passed_tasks,
        "failed_tasks": failed_tasks[:20],  # Keep only the first 20 failures.
    }
    
    # Write report.
    if args.output_file:
        output_file = args.output_file
    else:
        output_dir = os.path.dirname(args.results_file)
        output_file = os.path.join(output_dir, "evaluation_report.json")
    
    with open(output_file, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    # Print report.
    print("\n" + "=" * 80)
    print("📊 Evaluation report")
    print("=" * 80)
    print(f"Total records: {total}")
    print(f"Valid tests: {valid_total}")
    print(f"  ✓ Passed: {passed} ({pass_rate:.2f}%)")
    print(f"  ✗ Failed: {failed}")
    print()
    print("Issues:")
    print(f"  ⚠  Runtime errors: {run_error}")
    print(f"  ⚠  Empty responses: {no_response}")
    print(f"  ⚠  Parse errors: {parse_error}")
    print()
    
    if error_types:
        print("Error type breakdown:")
        for error_type, count in error_types.most_common():
            percentage = (count / failed * 100) if failed > 0 else 0
            print(f"  {error_type:20s}: {count:3d} ({percentage:.1f}%)")
        print()
    
    if failed_tasks and args.show_errors:
        print("Failed task details (first 10):")
        for task in failed_tasks[:10]:
            print(f"\n  {task['task_id']}")
            print(f"    Error type: {task['error_type']}")
            if task['error']:
                print(f"    Error: {task['error'][:150]}")
        print()
    
    print("=" * 80)
    print(f"📄 Detailed report saved to: {output_file}")
    print("=" * 80)
    
    return report


def main():
    try:
        report = evaluate_results()
        
        # Exit code.
        if report['pass_rate'] >= 50:
            sys.exit(0)
        else:
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n⚠  User interrupted")
        sys.exit(130)
    except Exception as e:
        print(f"❌ Execution failed: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
