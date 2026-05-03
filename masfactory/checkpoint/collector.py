class CheckpointCollector:
    
    def collect(self,root_graph):
        state={
            "graphs":{},
            "nodes":{},
            "edges":{},
            "components":{},
        }
        state["graphs"]["root"]=root_graph.get_checkpoint_state()

        for node_name,node in root_graph._nodes.items():
            node_id=f'root.{node_name}'
            state["nodes"][node_id]=node.get_checkpoint_state()
            self._collect_node_components(node,node_id,state)

        for index,edge in enumerate(root_graph._edges):
            edge_id=f'root.edge.{index}'
            state["edges"][edge_id]=edge.get_checkpoint_state()

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
