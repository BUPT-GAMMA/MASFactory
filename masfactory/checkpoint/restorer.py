class CheckpointRestorer:
    
    def restore(self,root_graph,state):

        root_graph.load_checkpoint_state(state["graphs"]["root"])

        for node_name,node in root_graph._nodes.items():
            node_id=f'root.{node_name}'
            node.load_checkpoint_state(state["nodes"][node_id])
            self._restore_node_components(node,node_id,state)

        for index,edge in enumerate(root_graph._edges):
            edge_id=f'root.edge.{index}'
            edge.load_checkpoint_state(state["edges"][edge_id])

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
