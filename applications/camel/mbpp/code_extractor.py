"""Extract Python code from CAMEL framework output - MBPP version."""

# Directly use code_extractor from eval directory
import sys
from pathlib import Path

# Add eval directory to path
eval_dir = Path(__file__).parent.parent / "eval"
if str(eval_dir) not in sys.path:
    sys.path.insert(0, str(eval_dir))

from code_extractor import (
    extract_python_code,
    extract_function_body_only,
    extract_completion_from_camel_result
)

__all__ = [
    "extract_python_code",
    "extract_function_body_only", 
    "extract_completion_from_camel_result"
]

