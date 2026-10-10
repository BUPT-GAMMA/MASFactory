class CheckpointRestorer:
    
    def restore(self,root_graph,state):
        self._restore_graph(root_graph,"root",state)

    def _restore_node_components(self,node,node_id,state):
        memories=getattr(node,"_memories",None)
        if memories:
            for index,memory in enumerate(memories):
                component_id=f'{node_id}.memories.{index}'
                if component_id in state["components"]:
                    memory.load_checkpoint_state(state["components"][component_id])
        
        history_memories=getattr(node,"_history_memories",None)
        if history_memories:
            for index,history in enumerate(history_memories):
                component_id=f'{node_id}.history_memories.{index}'
                if component_id in state["components"]:
                    history.load_checkpoint_state(state["components"][component_id])

        retrievers=getattr(node,"_retrievers",None)
        if retrievers:
            for index,retriever in enumerate(retrievers):
                component_id=f'{node_id}.retrievers.{index}'
                if component_id in state["components"]:
                    retriever.load_checkpoint_state(state["components"][component_id])                

    def _restore_graph(self,graph,graph_id,state):
        graph.load_checkpoint_state(state["graphs"][graph_id])

        for node_name,node in graph._nodes.items():
            node_id=f'{graph_id}.{node_name}'
            node.load_checkpoint_state(state["nodes"][node_id])
            self._restore_node_components(node,node_id,state)
            if hasattr(node,"_nodes") and hasattr(node,"_edges"):
                self._restore_graph(node,node_id,state)
        
        for index,edge in enumerate(graph._edges):
            edge_id=f'{graph_id}.edge.{index}'
            edge.load_checkpoint_state(state["edges"][edge_id])