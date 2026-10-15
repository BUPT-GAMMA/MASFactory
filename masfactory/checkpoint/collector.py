class CheckpointCollector:
    
    def collect(self,root_graph):
        state={
            "graphs":{},
            "nodes":{},
            "edges":{},
            "components":{},
        }
        self._collect_graph(root_graph,"root",state)
        return state
    
    def _collect_node_components(self, node, node_id: str, state: dict) -> None:
        memories = getattr(node, "_memories", None)
        if memories:
            for index, memory in enumerate(memories):
                component_id = f"{node_id}.memories.{index}"
                state["components"][component_id] = memory.get_checkpoint_state()

        history_memories = getattr(node, "_history_memories", None)
        if history_memories:
            for index, memory in enumerate(history_memories):
                component_id = f"{node_id}.history_memories.{index}"
                state["components"][component_id] = memory.get_checkpoint_state()

        retrievers = getattr(node, "_retrievers", None)
        if retrievers:
            for index, retriever in enumerate(retrievers):
                component_id = f"{node_id}.retrievers.{index}"
                state["components"][component_id] = retriever.get_checkpoint_state()

    def _collect_graph(self,graph,graph_id,state):
        state["graphs"][graph_id]=graph.get_checkpoint_state()

        for node_name,node in graph._nodes.items():
            node_id=f'{graph_id}.{node_name}'
            state["nodes"][node_id]=node.get_checkpoint_state()
            self._collect_node_components(node,node_id,state)
            if hasattr(node,"_nodes") and hasattr(node,"_edges"):
                self._collect_graph(node,node_id,state)
        
        for index,edge in enumerate(graph._edges):
            edge_id=f'{graph_id}.edge.{index}'
            state["edges"][edge_id]=edge.get_checkpoint_state()

