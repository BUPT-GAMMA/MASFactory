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
        self._resume_graph(self.root_graph)

        if self.root_graph._exit.is_ready:
            self.root_graph._exit.execute(self.root_graph.attributes)

        return self.root_graph._exit.output.copy(),self.root_graph.attributes.copy()
    
    def _resume_graph(self,graph):
        max_iterations=10000
        for _ in range(max_iterations):
            if graph._exit.is_ready or graph._gate !=Gate.OPEN:
                break
            
            executed_any = False
            for node in graph._nodes.values():
                if hasattr(node,"_nodes") and hasattr(node,"_edges"):
                    before_exit_ready=node._exit.is_ready
                    self._resume_graph(node)
                    if node._exit.is_ready and not before_exit_ready:
                        node._exit.execute(node.attributes)

                    if node._exit.output:
                        node._message_dispatch_out(node._exit.output)
                        executed_any=True
                        break

                if node.is_ready and graph._gate==Gate.OPEN:
                    node.execute(graph.attributes)
                    executed_any=True
                    break
            
            if not executed_any:
                break

        