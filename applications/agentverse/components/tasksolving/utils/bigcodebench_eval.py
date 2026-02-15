"""Vendored BigCodeBench local evaluator (minimal).

Kept self-contained to avoid importing from `original_dataset/bigcodebench` at runtime.
Adapted from BigCodeBench (MIT License).
"""

# The MIT License
#
# Copyright (c) OpenAI (https://openai.com)
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

from __future__ import annotations

import contextlib
import faulthandler
import io
import multiprocessing
import os
import platform
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from multiprocessing import Manager, Value
from pathlib import Path
from typing import Any


TIMEOUT_LIMIT = 240.0

PASS = "pass"
FAIL = "fail"
TIMEOUT = "timeout"

_SUCCESS = 0
_FAILED = 1
_TIMEOUT = 2
_UNKNOWN = 3

_mapping = {_SUCCESS: PASS, _FAILED: FAIL, _TIMEOUT: TIMEOUT, _UNKNOWN: None}


class TimeoutException(Exception):
    pass


class WriteOnlyStringIO(io.StringIO):
    """StringIO that throws an exception when it's read from."""

    def read(self, *args, **kwargs):  # type: ignore[override]
        raise IOError

    def readline(self, *args, **kwargs):  # type: ignore[override]
        raise IOError

    def readlines(self, *args, **kwargs):  # type: ignore[override]
        raise IOError

    def readable(self, *args, **kwargs):  # type: ignore[override]
        return False


class redirect_stdin(contextlib._RedirectStream):  # type: ignore[misc]
    _stream = "stdin"


@contextlib.contextmanager
def swallow_subprocess_output():
    """Context manager to swallow stdout/stderr for subprocesses."""

    original_popen = subprocess.Popen
    original_run = subprocess.run

    def _popen_patch(*args, **kwargs):
        if kwargs.get("capture_output"):
            kwargs.pop("stdout", None)
            kwargs.pop("stderr", None)
        else:
            kwargs.setdefault("stdout", subprocess.PIPE)
            kwargs.setdefault("stderr", subprocess.PIPE)
        return original_popen(*args, **kwargs)

    def _run_patch(*args, **kwargs):
        if kwargs.get("capture_output"):
            kwargs.pop("stdout", None)
            kwargs.pop("stderr", None)
        else:
            kwargs.setdefault("stdout", subprocess.PIPE)
            kwargs.setdefault("stderr", subprocess.PIPE)
        return original_run(*args, **kwargs)

    subprocess.Popen = _popen_patch
    subprocess.run = _run_patch
    try:
        yield
    finally:
        subprocess.Popen = original_popen
        subprocess.run = original_run


@contextlib.contextmanager
def swallow_io():
    stream = WriteOnlyStringIO()
    with contextlib.redirect_stdout(stream):
        with contextlib.redirect_stderr(stream):
            with redirect_stdin(stream):
                with swallow_subprocess_output():
                    yield


@contextlib.contextmanager
def time_limit(seconds: float):
    def signal_handler(signum, frame):  # noqa: ARG001
        raise TimeoutException("Timed out!")

    signal.setitimer(signal.ITIMER_REAL, seconds)
    signal.signal(signal.SIGALRM, signal_handler)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


@contextlib.contextmanager
def chdir(root: str):
    if root == ".":
        yield
        return
    cwd = os.getcwd()
    os.chdir(root)
    try:
        yield
    finally:
        os.chdir(cwd)


@contextlib.contextmanager
def create_tempdir():
    with tempfile.TemporaryDirectory() as dirname:
        with chdir(dirname):
            yield dirname


@contextlib.contextmanager
def safe_environment():
    """Best-effort guardrails to avoid destructive process operations.

    This is NOT a security sandbox. It matches BigCodeBench's local evaluator intent.
    """

    original_kill = os.kill
    original_killpg = os.killpg
    original_system = os.system
    original_subprocess_call = subprocess.call
    original_subprocess_check_output = subprocess.check_output
    original_subprocess_run = subprocess.run
    original_subprocess_popen = subprocess.Popen
    original_os_popen = os.popen
    original_os_execv = os.execv
    original_os_execvp = os.execvp
    original_os_execvpe = os.execvpe

    current_pid = os.getpid()
    current_pgid = os.getpgid(current_pid)
    child_pids: list[int] = []

    def safe_kill(pid, sig):
        try:
            if pid == current_pid or pid in child_pids:
                return original_kill(pid, sig)
        except ProcessLookupError:
            return None
        # Silently ignore attempts to kill other processes.
        return None

    def safe_killpg(pgid, sig):
        try:
            if pgid == current_pgid:
                return original_killpg(pgid, sig)
        except ProcessLookupError:
            return None
        return None

    def _looks_like_kill(cmd: Any) -> bool:
        try:
            if isinstance(cmd, (list, tuple)) and cmd:
                cmd0 = str(cmd[0])
                return cmd0 in {"kill", "killall"}
            if isinstance(cmd, str):
                return "kill" in cmd or "killall" in cmd
        except Exception:
            return False
        return False

    def safe_system(command):
        if _looks_like_kill(command):
            return 0
        return original_system(command)

    def safe_subprocess_call(command, *args, **kwargs):
        if _looks_like_kill(command):
            return 0
        return original_subprocess_call(command, *args, **kwargs)

    def safe_subprocess_check_output(command, *args, **kwargs):
        if _looks_like_kill(command):
            return b""
        return original_subprocess_check_output(command, *args, **kwargs)

    def safe_subprocess_run(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args")
        if _looks_like_kill(cmd):
            return subprocess.CompletedProcess(args, 0, b"", b"")
        return original_subprocess_run(*args, **kwargs)

    class SafePopen(subprocess.Popen):
        def __init__(self, *args, **kwargs):
            kwargs["preexec_fn"] = os.setsid  # Start the process in a new session
            super().__init__(*args, **kwargs)
            child_pids.append(self.pid)

        def kill(self):  # type: ignore[override]
            safe_kill(self.pid, signal.SIGTERM)

        def terminate(self):  # type: ignore[override]
            safe_kill(self.pid, signal.SIGTERM)

    def safe_os_popen(command):
        if _looks_like_kill(command):
            return original_os_popen("echo intercepted")
        return original_os_popen(command)

    def safe_exec(*args, **kwargs):  # noqa: ARG001
        return None

    os.kill = safe_kill
    os.killpg = safe_killpg
    os.system = safe_system
    subprocess.call = safe_subprocess_call
    subprocess.check_output = safe_subprocess_check_output
    subprocess.run = safe_subprocess_run
    subprocess.Popen = SafePopen
    os.popen = safe_os_popen
    os.execv = safe_exec
    os.execvp = safe_exec
    os.execvpe = safe_exec

    try:
        yield
    finally:
        os.kill = original_kill
        os.killpg = original_killpg
        os.system = original_system
        subprocess.call = original_subprocess_call
        subprocess.check_output = original_subprocess_check_output
        subprocess.run = original_subprocess_run
        subprocess.Popen = original_subprocess_popen
        os.popen = original_os_popen
        os.execv = original_os_execv
        os.execvp = original_os_execvp
        os.execvpe = original_os_execvpe


def reliability_guard(max_as_limit: float, max_data_limit: float, max_stack_limit: float) -> None:
    """Best-effort resource limits + disable obvious foot-guns.

    Limits are interpreted as MiB, matching BigCodeBench CLI defaults.
    """

    os.environ["TZ"] = "UTC"
    try:
        time.tzset()
    except Exception:
        pass

    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
    os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"

    if max_as_limit and max_data_limit and max_stack_limit:
        try:
            import resource  # Unix-only

            max_as_b = int(max_as_limit) * 1024 * 1024
            max_data_b = int(max_data_limit) * 1024 * 1024
            max_stack_b = int(max_stack_limit) * 1024 * 1024

            resource.setrlimit(resource.RLIMIT_AS, (max_as_b, max_as_b))
            resource.setrlimit(resource.RLIMIT_DATA, (max_data_b, max_data_b))
            if platform.uname().system != "Darwin":
                resource.setrlimit(resource.RLIMIT_STACK, (max_stack_b, max_stack_b))
        except Exception:
            # If we can't set rlimits (platform/permissions), continue without them.
            pass

    faulthandler.disable()

    import builtins

    builtins.exit = None
    builtins.quit = None

    # Optional cleanup (do not hard depend on matplotlib).
    try:
        import matplotlib.pyplot as plt  # type: ignore

        plt.close("all")
    except Exception:
        pass


def _parse_timeout_env(default: float) -> float:
    raw = os.getenv("BIGCODEBENCH_TIMEOUT_PER_TASK")
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def unsafe_execute(
    entry_point: str,
    code: str,
    test_code: str,
    timeout: float,
    max_as_limit: float,
    max_data_limit: float,
    max_stack_limit: float,
    stat,  # multiprocessing.Value
    details,  # multiprocessing.Manager().dict
) -> None:
    with safe_environment(), create_tempdir():
        import builtins
        import shutil

        # Disable functionalities that can make destructive changes to the test.
        reliability_guard(max_as_limit, max_data_limit, max_stack_limit)

        module_name = "__test__"
        new_module = types.ModuleType(module_name)
        new_module.__dict__.update(
            {
                "__builtins__": builtins,
                "__file__": f"{module_name}.py",
                "__package__": None,
                "__doc__": None,
                "sys": sys,
                "os": os,
                "environ": os.environ,
            }
        )

        # Ensure tempdir cleanup works even if user code clobbers these.
        rmtree = shutil.rmtree
        rmdir = os.rmdir
        chdir_fn = os.chdir

        try:
            full_code = str(code or "") + "\n" + str(test_code or "")
            with swallow_io():
                exec(compile(full_code, f"{module_name}.py", "exec"), new_module.__dict__)
                sys.modules[module_name] = new_module
                TestCases = getattr(new_module, "TestCases")
                loader = unittest.TestLoader()
                suite = loader.loadTestsFromTestCase(TestCases)
                test_result = unittest.TestResult()
                with time_limit(timeout):
                    suite.run(test_result)

            issues = list(test_result.failures) + list(test_result.errors)
            for test, trace in issues:
                try:
                    details[test.id().split(".")[-1]] = trace
                except Exception:
                    details["ALL"] = trace
            stat.value = _SUCCESS
        except TimeoutException as e:
            details["ALL"] = str(e)
            stat.value = _TIMEOUT
        except BaseException as e:
            details["ALL"] = str(e)
            stat.value = _FAILED
        finally:
            shutil.rmtree = rmtree
            os.rmdir = rmdir
            os.chdir = chdir_fn


def untrusted_check(
    code: str,
    test_code: str,
    entry_point: str,
    max_as_limit: float,
    max_data_limit: float,
    max_stack_limit: float,
    min_time_limit: float = 10,
    gt_time_limit: float = 60,
):
    """Run untrusted solution code + test code in an isolated process.

    Returns:
      (status, details_dict)
    """

    # BigCodeBench semantics: enforce a lower bound for timeout.
    min_time_limit = max(float(min_time_limit), float(gt_time_limit))
    timeout_env = _parse_timeout_env(TIMEOUT_LIMIT)
    timeout = max(timeout_env, min_time_limit) + 1

    stat = Value("i", _UNKNOWN)
    manager = Manager()
    details = manager.dict()

    p = multiprocessing.Process(
        target=unsafe_execute,
        args=(
            str(entry_point or "task_func"),
            str(code or ""),
            str(test_code or ""),
            timeout,
            float(max_as_limit),
            float(max_data_limit),
            float(max_stack_limit),
            stat,
            details,
        ),
    )
    p.start()
    p.join(timeout=timeout + 1)
    if p.is_alive():
        p.terminate()
        time.sleep(0.1)
    if p.is_alive():
        p.kill()
        time.sleep(0.1)

    mapped = _mapping.get(stat.value)
    details_dict = dict(details)
    if not mapped:
        mapped = TIMEOUT
    if mapped == PASS and details_dict:
        mapped = FAIL
    return mapped, details_dict
