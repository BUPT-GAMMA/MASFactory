from .workflow import BenchmarkCompletionGraph
class MATHCompletionGraph(BenchmarkCompletionGraph):
    def __init__(self, name: str = "math_completion", **kwargs): super().__init__(name, dataset="MATH", **kwargs)
__all__ = ["MATHCompletionGraph"]
