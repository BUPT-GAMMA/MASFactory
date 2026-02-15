import os
import sys
from pathlib import Path

# Ensure repo root is importable when running as a script.
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


class CoverageTestExecutor:
    """Compute concept coverage for text-generation solutions.

    This executor is primarily used for CommonGen-style tasks where the task
    description provides a list of concepts that the solution should cover.
    """
    
    def __init__(self):
        pass
    
    def execute(self, task_description, solution: str) -> str:
        """Run a coverage test for one solution.

        Args:
            task_description: A concept list (string "a, b, c" or an iterable).
            solution: Generated solution text.

        Returns:
            A formatted string containing coverage percentage and missing tokens.
        """
        try:
            # Prefer the same scoring implementation used by original AgentVerse.
            from scripts.evaluate_commongen import scoring

            concepts = task_description
            if isinstance(task_description, str):
                concepts = [c.strip() for c in task_description.split(",") if c.strip()]
            elif isinstance(task_description, (list, tuple, set)):
                concepts = [str(c).strip() for c in task_description if str(c).strip()]

            coverage, missing_tokens = scoring([solution], [concepts], verbose=False)

            if len(missing_tokens[0]) == 0:
                missing_tokens_str = "No missing tokens."
            else:
                missing_tokens_str = ", ".join(sorted(missing_tokens[0]))

            return f"Coverage: {coverage*100:.2f}%\nMissing Tokens: {missing_tokens_str}"

        except Exception:
            # If spaCy/scoring is unavailable, fall back to simple string matching.
            return self._simple_coverage_test(task_description, solution)

    def _simple_coverage_test(self, task_description, solution: str) -> str:
        """Fallback coverage test using string matching.

        Used when the primary scorer (e.g., spaCy-based) is unavailable.
        """
        # Normalize concepts.
        if isinstance(task_description, str):
            concepts = [c.strip().lower() for c in task_description.split(",") if c.strip()]
        elif isinstance(task_description, (list, tuple, set)):
            concepts = [str(c).strip().lower() for c in task_description if str(c).strip()]
        else:
            concepts = [str(task_description).strip().lower()] if str(task_description).strip() else []

        # Lowercase for matching.
        solution_lower = solution.lower()

        # Track covered vs. missing concepts.
        covered = []
        missing = []

        for concept in concepts:
            # Simple check: concept substring or a few common suffix variants.
            if concept in solution_lower:
                covered.append(concept)
            else:
                found = False
                for suffix in ['s', 'ed', 'ing', 'es', 'd']:
                    if concept + suffix in solution_lower:
                        covered.append(concept)
                        found = True
                        break
                if not found:
                    missing.append(concept)

        if len(concepts) > 0:
            coverage = len(covered) / len(concepts)
        else:
            coverage = 1.0

        if len(missing) == 0:
            missing_tokens_str = "No missing tokens."
        else:
            missing_tokens_str = ", ".join(sorted(missing))

        return (
            f"Coverage: {coverage*100:.2f}%\nMissing Tokens: {missing_tokens_str}\n"
            "(NOTE: simple string-matching fallback)"
        )
    
    def __call__(self, task_description: str, solution: str) -> str:
        return self.execute(task_description, solution)


def create_coverage_test_executor():
    return CoverageTestExecutor()
