class NoneExecutor:
    """No-op executor that returns the solution unchanged."""
    
    def __init__(self):
        pass
    
    def execute(self, task_description: str, solution: str) -> str:
        return solution
    
    def __call__(self, task_description: str, solution: str) -> str:
        return self.execute(task_description, solution)


def create_none_executor():
    return NoneExecutor()
