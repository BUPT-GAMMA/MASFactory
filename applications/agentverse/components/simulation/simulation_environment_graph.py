from typing import Dict, List, Optional, Any
from masfactory import Graph, Agent, CustomNode, Model
from masfactory.adapters.memory import HistoryMemory


class SimulationEnvironmentGraph(Graph):
    """Conversation simulation environment for multiple agents.

    Args:
        name: Graph name.
        agent_configs: Per-agent configs (name/role_description/instructions).
        model: Model adapter shared by agents.
        max_turns: Maximum number of dialogue turns.
        order_type: "sequential" | "random" | "concurrent" (currently falls back to sequential).
        visibility_type: Message visibility policy (currently unused).
        shared_memory: Whether agents share a HistoryMemory.
        pull_keys: Graph pull rule.
        push_keys: Graph push rule.
        attributes: Initial graph attributes.
    """
    
    def __init__(
        self,
        name: str,
        agent_configs: List[Dict[str, Any]],
        model: Model,
        max_turns: int = 10,
        order_type: str = "sequential",
        visibility_type: str = "all",
        shared_memory: bool = True,
        pull_keys: Optional[Dict[str, str]] = None,
        push_keys: Optional[Dict[str, str]] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            name=name,
            pull_keys=pull_keys if pull_keys is not None else {},
            push_keys=push_keys if push_keys is not None else {"conversation_history": "Complete conversation history"},
            attributes=attributes if attributes is not None else {}
        )
        
        self._agent_configs = agent_configs
        self._model = model
        self._max_turns = max_turns
        self._order_type = order_type
        self._visibility_type = visibility_type
        self._shared_memory = shared_memory
        
        # Internal state.
        self._agents: List[Agent] = []
        self._current_turn = 0
        self._next_agent_idx = 0
        self._conversation_history: List[Dict[str, str]] = []
        
        # Optional shared memory across agents.
        if self._shared_memory:
            self._shared_history = HistoryMemory()
        
        self._build_graph()
    
    def _build_graph(self):
        """Create internal nodes and wire the simulation graph."""
        for i, agent_config in enumerate(self._agent_configs):
            agent_name = agent_config.get("name", f"agent_{i}")
            role_description = agent_config.get("role_description", "")
            instructions = agent_config.get("instructions", "")
            
            # Default instructions (kept minimal and action-formatted).
            if not instructions:
                instructions = f"""{role_description}

When responding, output strictly in the following format:
Action: Speak
Action Input: (what you want to say)

Conversation history:
{{chat_history}}

Now respond based on the conversation history above. Remember to follow the format strictly."""
            
            # Create agents with shared or independent memory.
            if self._shared_memory:
                memory = self._shared_history
            else:
                memory = HistoryMemory()
            
            agent = self.create_node(
                Agent,
                name=f"{self.name}_{agent_name}",
                role_name=agent_name,
                instructions=instructions,
                model=self._model,
                memory=memory,
                pull_keys=None,  # Pull all attributes.
                push_keys={"message": f"Message from {agent_name}"},
                output_keys={"message": "Agent response"},
            )
            
            self._agents.append(agent)
        
        def control_turns(messages: dict, attributes: dict) -> dict:
            # Read current turn and conversation history.
            current_turn = attributes.get("current_turn", 0)
            conversation_history = attributes.get("conversation_history", [])
            
            # Append the latest message (if any).
            if "message" in messages and messages["message"]:
                last_speaker = attributes.get("last_speaker", "Unknown")
                conversation_history.append({
                    "speaker": last_speaker,
                    "message": messages["message"]
                })
            
            # Stop when max turns is reached.
            if current_turn >= self._max_turns:
                return {
                    "conversation_history": conversation_history,
                    "finished": True,
                    "current_turn": current_turn
                }
            
            # Select next speaker.
            if self._order_type == "sequential":
                next_agent_idx = current_turn % len(self._agents)
            elif self._order_type == "random":
                import random
                next_agent_idx = random.randint(0, len(self._agents) - 1)
            elif self._order_type == "concurrent":
                # Concurrent mode is not implemented yet; fall back to sequential.
                next_agent_idx = current_turn % len(self._agents)
            else:
                next_agent_idx = current_turn % len(self._agents)
            
            # Format chat history for the next agent prompt.
            chat_history = "\n".join([
                f"{entry['speaker']}: {entry['message']}"
                for entry in conversation_history
            ])
            
            next_agent_name = self._agent_configs[next_agent_idx].get("name", f"agent_{next_agent_idx}")
            
            return {
                "conversation_history": conversation_history,
                "chat_history": chat_history,
                "next_agent_idx": next_agent_idx,
                "next_agent_name": next_agent_name,
                "last_speaker": next_agent_name,
                "current_turn": current_turn + 1,
                "finished": False
            }
        
        turn_controller = self.create_node(
            CustomNode,
            name=f"{self.name}_turn_controller",
            forward=control_turns,
            pull_keys=None,
            push_keys=None
        )
        
        def route_to_agent(messages: dict, attributes: dict) -> dict:
            next_agent_idx = attributes.get("next_agent_idx", 0)
            chat_history = attributes.get("chat_history", "")
            
            return {
                "chat_history": chat_history,
                "agent_idx": next_agent_idx
            }
        
        message_router = self.create_node(
            CustomNode,
            name=f"{self.name}_message_router",
            forward=route_to_agent,
            pull_keys=None,
            push_keys=None
        )
        
        # Wire edges.
        self.edge_from_entry(
            receiver=turn_controller,
            keys={}
        )
        
        self.create_edge(
            sender=turn_controller,
            receiver=message_router,
            keys={}
        )
        
        # NOTE: This connects to all agents and relies on attributes to decide which
        # one should act. A full implementation would route only to the selected agent.
        for agent in self._agents:
            self.create_edge(
                sender=message_router,
                receiver=agent,
                keys={}
            )
            
            self.create_edge(
                sender=agent,
                receiver=turn_controller,
                keys={"message": "Agent response"}
            )
        
        self.edge_to_exit(
            sender=turn_controller,
            keys={"conversation_history": "Complete conversation history"}
        )
