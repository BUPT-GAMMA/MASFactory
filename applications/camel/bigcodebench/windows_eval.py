"""Windows-compatible BigCodeBench evaluation module."""

import contextlib
import faulthandler
import io
import multiprocessing
import os
import platform
import tempfile
import threading
import time
import types
import unittest
from typing import Dict, Optional, Tuple, Any
import sys


class TimeoutException(Exception):
    pass


def unsafe_execute_bigcodebench(
    entry_point: str,
    code: str,
    test_code: str,
    timeout: float,
    result_dict: Dict[str, Any],
):
    """Windows-compatible code execution function."""
    try:
        with create_tempdir():
            import os
            import shutil
            import builtins
            
            rmtree = shutil.rmtree
            rmdir = os.rmdir
            chdir = os.chdir
            
            # Disable functionalities that can make destructive changes to the test.
            reliability_guard()
            
            module_name = "__test__"
            new_module = types.ModuleType(module_name)
            # Set necessary attributes for the module
            new_module.__dict__.update({
                '__builtins__': builtins,
                '__file__': f"{module_name}.py",
                '__package__': None,
                '__doc__': None,
                'sys': sys,
                'os': os,
                'environ': os.environ,
            })
            
            try:
                full_code = code + "\n" + test_code
                
                with swallow_io():
                    with time_limit(timeout):
                        exec(compile(full_code, f"{module_name}.py", 'exec'), new_module.__dict__)
                        sys.modules[module_name] = new_module
                        TestCases = getattr(new_module, 'TestCases')
                        loader = unittest.TestLoader()
                        suite = loader.loadTestsFromTestCase(TestCases)
                        test_result = unittest.TestResult()
                        suite.run(test_result)
                
                issues = test_result.failures + test_result.errors
                if issues:
                    result_dict["status"] = "fail"
                    result_dict["details"] = {test.id().split(".")[-1]: trace for test, trace in issues}
                else:
                    result_dict["status"] = "pass"
                    result_dict["details"] = {}
            except TimeoutException:
                result_dict["status"] = "timeout"
                result_dict["details"] = {"ALL": "Timed out!"}
            except BaseException as e:
                result_dict["status"] = "fail"
                result_dict["details"] = {"ALL": str(e)}
            finally:
                # Needed for cleaning up.
                shutil.rmtree = rmtree
                os.rmdir = rmdir
                os.chdir = chdir
    except Exception as e:
        result_dict["status"] = "fail"
        result_dict["details"] = {"ALL": f"Execution error: {str(e)}"}


def check_bigcodebench_correctness_windows(
    code: str,
    test_code: str,
    entry_point: str,
    timeout: float = 240.0,
) -> Tuple[str, Dict[str, str]]:
    """
    Windows-compatible BigCodeBench code correctness check function.
    
    Returns:
        Tuple of (status, details), where status is "pass"/"fail"/"timeout"
    """
    # On Windows, use subprocess to execute code, which provides better timeout control
    import subprocess
    import tempfile
    
    result_dict = {}
    
    try:
        # Create temporary Python file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            # Write complete code (including tests)
            # If code uses matplotlib, need to set non-interactive backend to avoid hanging in subprocess
            matplotlib_setup = ""
            if "matplotlib" in code or "plt." in code or "import matplotlib" in code:
                matplotlib_setup = "import matplotlib\nmatplotlib.use('Agg')\n"
            
            # Remove plt.show() calls, as they're not needed in non-interactive backend and may cause hanging
            # Use regex to replace plt.show() with comment
            import re
            cleaned_code = code
            if "plt.show()" in cleaned_code:
                # Replace plt.show() with comment, preserving original indentation and newlines
                # Match: optional whitespace + plt.show() + optional whitespace + optional newline
                cleaned_code = re.sub(r'(\s*)plt\.show\(\)(\s*\n?)', r'\1# plt.show()  # Removed, using non-interactive backend\2', cleaned_code)
            
            # Ensure test code will run
            # BigCodeBench test code is unittest.TestCase class, need to run tests
            # If test code doesn't have code to run tests, add runner code
            test_runner = ""
            if "if __name__" not in test_code and "__main__" not in test_code:
                # If test code doesn't run tests, add runner code
                test_runner = "\n\nif __name__ == '__main__':\n    import unittest\n    unittest.main()\n"
            
            full_code = matplotlib_setup + cleaned_code + "\n" + test_code + test_runner
            f.write(full_code)
            temp_file = f.name
        
        try:
            # Use subprocess to execute, set timeout
            result = subprocess.run(
                [sys.executable, temp_file],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tempfile.gettempdir()
            )
            
            if result.returncode == 0:
                # Execution successful, check test results
                # unittest returns 0 on success, also returns 0 on failure (but will have output)
                # Check if output contains failure information
                output = result.stdout + result.stderr
                if "FAILED" in output.upper() or "FAILURES" in output.upper() or "ERRORS" in output.upper():
                    result_dict["status"] = "fail"
                    result_dict["details"] = {"ALL": output[:500]}
                elif "OK" in output or "Ran" in output:
                    # Has test run information, check if there are failures
                    if "failures=" in output.lower() or "errors=" in output.lower():
                        # Extract failure count
                        import re
                        failures_match = re.search(r'failures=(\d+)', output.lower())
                        errors_match = re.search(r'errors=(\d+)', output.lower())
                        failures = int(failures_match.group(1)) if failures_match else 0
                        errors = int(errors_match.group(1)) if errors_match else 0
                        if failures > 0 or errors > 0:
                            result_dict["status"] = "fail"
                            result_dict["details"] = {"ALL": output[:500]}
                        else:
                            result_dict["status"] = "pass"
                            result_dict["details"] = {}
                    else:
                        result_dict["status"] = "pass"
                        result_dict["details"] = {}
                else:
                    # No clear test output, should be judged as failure or unknown
                    # Because unittest should always have output, no output may mean:
                    # 1. Test code didn't execute correctly
                    # 2. Test code has errors but was silently handled
                    # 3. Output was redirected or lost
                    # For stricter judgment, we judge as failure
                    result_dict["status"] = "fail"
                    result_dict["details"] = {"ALL": "No test output detected. unittest should always produce output."}
            else:
                # Execution failed (syntax error, runtime error, etc.)
                error_msg = result.stderr[:500] if result.stderr else result.stdout[:500]
                result_dict["status"] = "fail"
                result_dict["details"] = {"ALL": error_msg or "Execution failed"}
        except subprocess.TimeoutExpired:
            result_dict["status"] = "timeout"
            result_dict["details"] = {"ALL": "Process timeout"}
        except Exception as e:
            result_dict["status"] = "fail"
            result_dict["details"] = {"ALL": f"Execution error: {str(e)[:500]}"}
        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_file)
            except:
                pass
    except Exception as e:
        result_dict["status"] = "fail"
        result_dict["details"] = {"ALL": f"Setup error: {str(e)[:500]}"}
    
    status = result_dict.get("status", "timeout")
    details = dict(result_dict.get("details", {}))
    
    # Convert to bigcodebench format
    if status == "pass":
        return "pass", details
    elif status == "timeout":
        return "timeout", details
    else:
        return "fail", details


@contextlib.contextmanager
def time_limit(seconds: float):
    """Windows-compatible timeout mechanism."""
    if platform.system() == "Windows":
        # Windows uses threading to implement timeout
        timer = None
        exception_raised = threading.Event()
        
        def timeout_handler():
            exception_raised.set()
            raise TimeoutException("Timed out!")
        
        timer = threading.Timer(seconds, timeout_handler)
        timer.daemon = True
        timer.start()
        try:
            yield
        except TimeoutException:
            raise
        finally:
            timer.cancel()
    else:
        # Unix systems use signal
        import signal
        def signal_handler(signum, frame):
            raise TimeoutException("Timed out!")
        
        signal.setitimer(signal.ITIMER_REAL, seconds)
        signal.signal(signal.SIGALRM, signal_handler)
        try:
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)


@contextlib.contextmanager
def swallow_io():
    stream = WriteOnlyStringIO()
    with contextlib.redirect_stdout(stream):
        with contextlib.redirect_stderr(stream):
            with redirect_stdin(stream):
                yield


@contextlib.contextmanager
def create_tempdir():
    with tempfile.TemporaryDirectory() as dirname:
        with chdir(dirname):
            yield dirname


class WriteOnlyStringIO(io.StringIO):
    """StringIO that throws an exception when it's read from"""

    def read(self, *args, **kwargs):
        raise IOError

    def readline(self, *args, **kwargs):
        raise IOError

    def readlines(self, *args, **kwargs):
        raise IOError

    def readable(self, *args, **kwargs):
        """Returns True if the IO object can be read."""
        return False


class redirect_stdin(contextlib._RedirectStream):  # type: ignore
    _stream = "stdin"


@contextlib.contextmanager
def chdir(root):
    if root == ".":
        yield
        return
    cwd = os.getcwd()
    os.chdir(root)
    try:
        yield
    except BaseException as exc:
        raise exc
    finally:
        os.chdir(cwd)


def reliability_guard(max_as_limit: Optional[int] = None, max_data_limit: Optional[int] = None, max_stack_limit: Optional[int] = None):
    """
    Windows-compatible reliability guard function.
    Note: On Windows, we only disable the most dangerous functions, keeping necessary functionality (like chdir) so tests can run.
    """
    faulthandler.disable()
    
    import builtins
    builtins.exit = None
    builtins.quit = None
    
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ['TF_CPP_MIN_LOG_LEVEL'] = "3"
    os.environ['TF_ENABLE_ONEDNN_OPTS'] = "0"
    
    # Windows doesn't support resource module, skip resource limit settings
    if platform.system() != "Windows" and max_as_limit and max_data_limit and max_stack_limit:
        try:
            import resource
            max_as_limit = max_as_limit * 1024 * 1024
            max_data_limit = max_data_limit * 1024 * 1024
            max_stack_limit = max_stack_limit * 1024 * 1024
            
            resource.setrlimit(
                resource.RLIMIT_AS, (max_as_limit, max_as_limit)
            )
            resource.setrlimit(
                resource.RLIMIT_DATA, (max_data_limit, max_data_limit)
            )
            if not platform.uname().system == "Darwin":
                resource.setrlimit(
                    resource.RLIMIT_STACK, (max_stack_limit, max_stack_limit)
                )
        except (ImportError, AttributeError):
            pass  # resource module not available on Windows
    
    # Disable dangerous functions (but keep chdir and other necessary functions, as tests need them)
    if hasattr(os, 'kill'):
        os.kill = None
    if hasattr(os, 'killpg'):
        os.killpg = None
    os.system = None
    os.putenv = None
    # Note: Don't disable os.remove, os.rmdir, etc., as test code may need them
    # os.remove = None
    # os.removedirs = None
    # os.rmdir = None
    os.fchdir = None
    if hasattr(os, 'setuid'):
        os.setuid = None
    if hasattr(os, 'fork'):
        os.fork = None
    if hasattr(os, 'forkpty'):
        os.forkpty = None
    # Note: Don't disable os.rename, etc., as tests may need them
    # os.rename = None
    # os.renames = None
    os.truncate = None
    # os.replace = None
    # os.unlink = None
    os.fchmod = None
    os.fchown = None
    os.chmod = None
    os.chown = None
    os.chroot = None
    os.lchflags = None
    os.lchmod = None
    os.lchown = None
    # Note: Keep os.getcwd and os.chdir, as tests need them
    # os.getcwd = None
    # os.chdir = None
    
    import shutil
    # Note: Don't disable all of shutil, as tests may need it
    # shutil.rmtree = None
    # shutil.move = None
    shutil.chown = None
    
    import subprocess
    # Note: Don't disable subprocess.Popen, as some tests may need it
    # subprocess.Popen = None  # type: ignore
    
    __builtins__["help"] = None
    
    import sys
    sys.modules["ipdb"] = None
    sys.modules["joblib"] = None
    sys.modules["resource"] = None
    sys.modules["psutil"] = None
    sys.modules["tkinter"] = None
    
    try:
        import matplotlib.pyplot as plt
        plt.close('all')
    except ImportError:
        pass
