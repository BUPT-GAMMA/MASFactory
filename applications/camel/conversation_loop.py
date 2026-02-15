"""Conversation loop component: implements continuous dialogue between AI User and AI Assistant.

This module provides the ConversationLoop class, which manages the iterative conversation
between two agents until the task is completed or maximum iterations are reached.
"""

from masfactory.components.graphs.loop import Loop
from masfactory.components.agents.agent import Agent
from masfactory.adapters.model import Model
from masfactory.adapters.memory import HistoryMemory
from masfactory.core.node import Node
from typing import Dict
from masfactory.utils.hook import masf_hook
from camel_formatter import CamelMessageFormatter


class CamelAgentWrapper(Agent):
    """Wrapper for Agent that dynamically sets required_keys in _forward method."""
    def _forward(self, input: Dict[str, object]) -> Dict[str, object]:
        if hasattr(self._out_formatter, '_required_keys'):
            output_keys_set = set(self.output_keys.keys())
            self._out_formatter._required_keys = output_keys_set
        
        return super()._forward(input)


class ConversationLoop(Loop):
    """Conversation loop: implements continuous interaction between two agents until task completion."""
    
    def __init__(
        self,
        name: str,
        model: Model,
        max_iterations: int = 50,
        pull_keys: Dict[str, str] = None,
        push_keys: Dict[str, str] = None,
        attributes: Dict[str, object] = {},
        tools: list = None,
    ):
        def terminate_condition_function(input_dict: Dict[str, object], attributes_store: Dict[str, object], loop_node) -> bool:
            if hasattr(loop_node, '_should_terminate') and loop_node._should_terminate:
                return True
            
            if hasattr(loop_node, '_current_iteration') and hasattr(loop_node, '_max_iterations'):
                current_iter = getattr(loop_node, '_current_iteration', 0)
                max_iter = getattr(loop_node, '_max_iterations', max_iterations)
                if current_iter > max_iter:
                    return True
            
            user_message = input_dict.get("user_message", "")
            if isinstance(user_message, dict):
                user_message = str(user_message.get("user_message", user_message))
            else:
                user_message = str(user_message)
            
            user_message_upper = user_message.upper().strip()
            
            if "<CAMEL_TASK_DONE>" in user_message_upper or "CAMEL_TASK_DONE" in user_message_upper:
                return True
            
            assistant_message = input_dict.get("assistant_message", "")
            if isinstance(assistant_message, dict):
                assistant_message = str(assistant_message.get("assistant_message", assistant_message))
            else:
                assistant_message = str(assistant_message)
            
            assistant_message_upper = assistant_message.upper()
            completion_keywords = [
                "task is completed", "task has been completed", "task completed", 
                "completed successfully", "all done", "finished", "task is done",
                "implementation is complete", "bot is ready", "ready to use"
            ]
            if any(keyword in assistant_message_upper for keyword in completion_keywords):
                if "next request" not in assistant_message_upper.lower():
                    return True
            
            if hasattr(loop_node, '_current_iteration') and hasattr(loop_node, '_max_iterations'):
                current_iter = getattr(loop_node, '_current_iteration', 0)
                max_iter = getattr(loop_node, '_max_iterations', max_iterations)
                if current_iter >= max_iter * 0.95:
                    if any(keyword in assistant_message_upper for keyword in ["complete", "done", "finished", "ready"]):
                        return True
            
            return False
        
        from prompts import INIT_MESSAGE_CONTENT
        initial_messages = {
            "user_message": "", 
            "assistant_message": "", 
            "assistant_message_for_user": INIT_MESSAGE_CONTENT
        }
        
        super().__init__(
            name=name,
            max_iterations=max_iterations,
            model=model,
            terminate_condition_function=terminate_condition_function,
            pull_keys=pull_keys,
            push_keys=push_keys,
            attributes=attributes,
            initial_messages=initial_messages,
        )
        
        self._conversation_history = []
        self._model = model
        self._max_iterations = max_iterations
        self._should_terminate = False
        self._completion_signals = []  # Track completion signals from Assistant
        self.user_agent = None
        self.assistant_agent = None
        self.message_updater = None
        self._tools = tools or []
    
    @masf_hook(Node.Hook.FORWARD)
    def _forward(self, input: Dict[str, object]) -> Dict[str, object]:
        assistant_prompt = input.get("assistant_system_prompt", "")
        user_prompt = input.get("user_system_prompt", "")
        
        if assistant_prompt:
            self.assistant_agent._instructions = assistant_prompt
        if user_prompt:
            self.user_agent._instructions = user_prompt
        
        result = super()._forward(input)
        result["conversation_history"] = self._conversation_history.copy()
        
        if "assistant_role_name" in input:
            result["assistant_role_name"] = input["assistant_role_name"]
        if "user_role_name" in input:
            result["user_role_name"] = input["user_role_name"]
        if "task" in input:
            result["task"] = input["task"]
        
        if self._push_keys and len(self._push_keys) > 0:
            filtered_result = {}
            for key in self._push_keys.keys():
                if key in result:
                    filtered_result[key] = result[key]
            if "conversation_history" in result:
                filtered_result["conversation_history"] = result["conversation_history"]
            return filtered_result
        
        return result
    
    @masf_hook(Node.Hook.BUILD)
    def build(self):
        if self._is_built:
            return
        
        user_formatter = CamelMessageFormatter(output_key="user_message", required_keys=None)
        self.user_agent = self.create_node(
            CamelAgentWrapper,
            name="ai_user",
            model=self._model,
            instructions="",
            formatters=user_formatter,
            prompt_template="{assistant_message_for_user}",
            memories=[HistoryMemory(top_k=100, memory_size=1000)],
            pull_keys={
                "user_system_prompt": "System prompt for AI User",
                "assistant_message_for_user": "Previous message from AI Assistant to respond to",
            },
            push_keys={"user_message": "Message from AI User"},
            attributes={"role_name": "AI User"},
        )
        
        assistant_formatter = CamelMessageFormatter(output_key="assistant_message", required_keys=None)
        self.assistant_agent = self.create_node(
            CamelAgentWrapper,
            name="ai_assistant",
            model=self._model,
            instructions="",
            formatters=assistant_formatter,
            prompt_template="{user_message}",
            memories=[HistoryMemory(top_k=100, memory_size=1000)],
            tools=self._tools,
            pull_keys={
                "assistant_system_prompt": "System prompt for AI Assistant",
                "user_message": "Previous message from AI User",
            },
            push_keys={"assistant_message": "Message from AI Assistant"},
            attributes={"role_name": "AI Assistant"},
        )
        
        from masfactory.components.custom_node import CustomNode
        def message_updater_forward(input_dict):
            user_msg = input_dict.get("user_message", "")
            assistant_msg = input_dict.get("assistant_message", "")
            
            user_msg_str = str(user_msg) if user_msg else ""
            assistant_msg_str = str(assistant_msg) if assistant_msg else ""
            
            # Detect repetitive content (prevent infinite loops)
            if not hasattr(self, '_recent_messages'):
                self._recent_messages = []
            
            # Check if User message is repetitive
            if user_msg_str.strip():
                # Check if last 3 User messages are similar
                recent_user_msgs = [msg.get("content", "") for msg in self._conversation_history[-6:] if msg.get("role") == "AI User"]
                if len(recent_user_msgs) >= 3:
                    # Check if first 100 characters of last 3 messages are similar
                    recent_prefixes = [msg[:100].lower().strip() for msg in recent_user_msgs[-3:]]
                    if len(set(recent_prefixes)) == 1:  # Identical
                        # Detected repetitive User messages, force task completion
                        self._should_terminate = True
                        user_msg_str = "<CAMEL_TASK_DONE>"
                
                self._conversation_history.append({
                    "role": "AI User",
                    "content": user_msg_str
                })
                
                user_msg_upper = user_msg_str.upper().strip()
                if "<CAMEL_TASK_DONE>" in user_msg_upper or "CAMEL_TASK_DONE" in user_msg_upper:
                    if not hasattr(self, '_should_terminate'):
                        self._should_terminate = True
            
            # Check if Assistant message is repetitive
            if assistant_msg_str.strip():
                # Check if last 3 Assistant messages are similar
                recent_assistant_msgs = [msg.get("content", "") for msg in self._conversation_history[-6:] if msg.get("role") == "AI Assistant"]
                if len(recent_assistant_msgs) >= 3:
                    recent_prefixes = [msg[:200].lower().strip() for msg in recent_assistant_msgs[-3:]]
                    # If first 200 characters are very similar, consider it repetitive
                    if len(set(recent_prefixes)) <= 1:
                        # Detected repetitive Assistant messages, add warning
                        assistant_msg_str += "\n\n[WARNING: Your previous responses were very similar. Please try a different approach or indicate if you cannot proceed further.]"
                
                self._conversation_history.append({
                    "role": "AI Assistant",
                    "content": assistant_msg_str
                })
                
                assistant_msg_lower = assistant_msg_str.lower()
                completion_indicators = [
                    "task is complete", "task has been completed", "task completed",
                    "fully implemented", "all requirements are met", "core functionality is complete",
                    "essential requirements", "main task is done", "completed task",
                    "task confirmation", "task summary", "completed this step successfully",
                    "fully completed", "all done", "task finished",
                    "final answer", "the answer is", "answer:", "result:",
                    "the final answer is", "final answer:", "answer is", "result is",
                    "conclusion:", "summary:", "the answer", "the result"
                ]
                if any(indicator in assistant_msg_lower for indicator in completion_indicators):
                    self._completion_signals.append(len(self._conversation_history))
                    if len(self._completion_signals) >= 2:
                        self._should_terminate = True
                    elif len(self._completion_signals) >= 1 and "next request" not in assistant_msg_lower:
                        self._should_terminate = True
            
            current_round = len(self._conversation_history) // 2
            max_rounds = self._max_iterations
            
            # If over 60% of rounds, add warning
            if current_round >= max_rounds * 0.6:
                if len(self._completion_signals) >= 1:
                    warning_msg = f"\n\n[IMPORTANT: The Assistant has indicated that the task may be complete. Please review the solutions provided. If the core task is done, you MUST send <CAMEL_TASK_DONE> immediately. The conversation will be forced to end at round {max_rounds}.]\n"
                else:
                    warning_msg = f"\n\n[IMPORTANT WARNING: You have reached round {current_round} out of {max_rounds} maximum rounds. Please evaluate if the task is complete and send <CAMEL_TASK_DONE> immediately if the task is done. Otherwise, the conversation will terminate automatically at round {max_rounds}.]\n"
                assistant_msg_for_user = assistant_msg_str + warning_msg
            else:
                assistant_msg_for_user = assistant_msg_str
            
            return {
                "user_message": user_msg,
                "assistant_message": assistant_msg,
                "assistant_message_for_user": assistant_msg_for_user
            }
        
        self.message_updater = self.create_node(
            CustomNode,
            name="message_updater",
            forward=message_updater_forward,
            pull_keys={
                "user_message": "Message from AI User",
                "assistant_message": "Message from AI Assistant"
            },
            push_keys={
                "user_message": "Message from AI User",
                "assistant_message": "Message from AI Assistant",
                "assistant_message_for_user": "Message to send to User Agent"
            },
        )
        
        self.edge_from_controller(
            receiver=self.user_agent,
            keys={
                "user_system_prompt": "System prompt for AI User",
                "assistant_message_for_user": "Previous message from AI Assistant to respond to",
            }
        )
        
        self.create_edge(
            sender=self.user_agent,
            receiver=self.assistant_agent,
            keys={"user_message": "Message from AI User"},
        )
        
        self.create_edge(
            sender=self.user_agent,
            receiver=self.message_updater,
            keys={"user_message": "Message from AI User"},
        )
        
        self.create_edge(
            sender=self.assistant_agent,
            receiver=self.message_updater,
            keys={"assistant_message": "Message from AI Assistant"},
        )
        
        self.edge_to_controller(
            sender=self.message_updater,
            keys={
                "user_message": "Message from AI User",
                "assistant_message": "Message from AI Assistant",
                "assistant_message_for_user": "Message to send to User Agent"
            },
        )
        
        super().build()