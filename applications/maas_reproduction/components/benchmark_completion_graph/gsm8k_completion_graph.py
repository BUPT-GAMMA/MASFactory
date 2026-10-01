from .workflow import BenchmarkCompletionGraph
class GSM8KCompletionGraph(BenchmarkCompletionGraph):
    def __init__(self, name: str = "gsm8k_completion", **kwargs): super().__init__(name, dataset="GSM8K", **kwargs)
__all__ = ["GSM8KCompletionGraph"]
