from masfactory.core.node import Node
from masfactory.core.gate import Gate
from masfactory.checkpoint.collector import CheckpointCollector
from masfactory.checkpoint.restorer import CheckpointRestorer

class CheckpointManager:

    def __init__(self,root_graph,storage):
        self.collector=CheckpointCollector()
        self.restorer=CheckpointRestorer()
        self.root_graph=root_graph
        self.storage=storage
        self.last_checkpoint_path=None

    def save(self,trigger=None):
        checkpoint_state=self.collector.collect(self.root_graph)
        path_str=self.storage.save(checkpoint_state)
        self.last_checkpoint_path=path_str
        return path_str
    
    def load(self,checkpoint_path):
        checkpoint_state=self.storage.load(checkpoint_path)
        self.restorer.restore(self.root_graph,checkpoint_state)
        self.last_checkpoint_path = checkpoint_path
        return checkpoint_state

    def load_last(self):
        path_str=self.storage.get_last_path()
        if path_str is None:
            raise FileNotFoundError("No checkpoint file found.")
        return self.load(path_str)

    def attach_hooks(self):
        self.root_graph.hook_register(
            Node.Hook.EXECUTE.AFTER,
            self._save_after_execute,
            recursion=True
        )
    
    def _save_after_execute(self,node,result,outer_env=None):
        self.save(trigger=node)

    def resume(self):
        graph=self.root_graph
        max_iterations=10000
        for _ in range(max_iterations):
            if graph._exit.is_ready or graph._gate !=Gate.OPEN:
                break
            
            executed_any = False
            for node in graph._nodes.values():
                if node.is_ready and graph._gate==Gate.OPEN:
                    node.execute(graph.attributes)
                    executed_any=True
                    break
            
            if not executed_any:
                break
        if graph._exit.is_ready:
            graph._exit.execute(graph.attributes)
        return graph._exit.output.copy(),graph.attributes.copy()