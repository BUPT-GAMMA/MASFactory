from masfactory import Graph, Model, Memory, CustomNode, LogicSwitch, Loop,Node, masf_hook
from typing import Dict, Type
from collections import defaultdict
import logging
import os

logger = logging.getLogger(__name__)

class ComposedPhase(Graph):
    def __init__(
        self,
        name: str,                          # Composed phase name
        cycle_num: int,                     # Number of cycles
        composition: list,                  # List of Phase components
        phase_classes: Dict[str, Type],     # Phase subclasses {phase_name: PhaseClass}
        phase_configs: Dict[str, dict],     # Phase class configs {phase_name: config}
        model: Model,                       # Model instance
        memory: Memory,                     # MemoryAdapter instance (vector memory)
        reflect_roles: dict | None = None,  # 
    ):
        """
        Initialize composed phase

        Args:
            name: Composed phase name
            cycle_num: Maximum number of cycles
            composition: List of simple phase configurations, each containing phase, max_turn_step, need_reflect
            phase_classes: Dictionary of simple phase classes
            phase_configs: Dictionary of simple phase configurations
            model: Model instance
            memory: Shared memory instance
            reflect_roles: Reflection role configuration (includes ceo and counselor)
        """
        super().__init__(name)

        self._cycle_num = cycle_num
        self._composition = composition
        self._phase_classes = phase_classes
        self._phase_configs = phase_configs
        self._model = model
        self._memory = memory
        self._reflect_roles = reflect_roles

        # Attributes to be set by subclasses
        self._pre_loop_action_func = None      # Pre-loop processing function
        self._post_loop_action_func = None     # Post-loop processing function
        self._break_condition_func = None      # Loop break condition function

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        assert self._pull_keys is not None, "pull_keys must be provided"
        assert self._push_keys is not None, "push_keys must be provided"

        # Pre-loop processing node
        pre_loop_action = self.create_node(
            CustomNode,
            name=self._name + "_pre_loop_action",
            forward=self._pre_loop_action_func 
        )

        # Post-loop processing node
        post_loop_action = self.create_node(
            CustomNode,
            name=self._name + "_post_loop_action",
            forward=self._post_loop_action_func 
        )
        # Loop node
        loop = self.create_node(
            Loop,
            name=self._name + "_loop",
            max_iterations=self._cycle_num * len(self._composition),
            terminate_condition_function=self._break_condition_func,
            attributes={"cycle_num": self._cycle_num}
        )

        # Create round_control_switch inside loop
        round_control_switch = loop.create_node(  # Create inside loop
            LogicSwitch,
            name=self._name + "_round_control_switch"
        )
        
        def round_control_switch_condition_factory(index:int,max_index:int):
            # cycle_index and phase_turn start from 1
            def round_control_switch_condition(messages: dict, attributes: dict):
                nonlocal index
                if index == 1:
                    attributes["cycle_index"] = attributes.get("cycle_index", 0) + 1
                current_phase_turn = attributes.get("current_phase_turn", 1)
                attributes["current_phase_turn"] = current_phase_turn + 1 if current_phase_turn <= max_index else 1
                return current_phase_turn == index
            return round_control_switch_condition
        
        index = 0
        max_index = len(self._composition)
        for phase_item in self._composition:
            index += 1
            phase_name = phase_item['phase']
            max_turn_step = phase_item.get('max_turn_step', 10)
            need_reflect = phase_item.get('need_reflect', 'False').lower() == 'true'

            # Get phase class and config
            if phase_name not in self._phase_classes:
                raise ValueError(f"Phase '{phase_name}' not found in phase_classes")

            phase_class = self._phase_classes[phase_name]
            phase_config = self._phase_configs.get(phase_name, {})

            # Create simple phase instance
            phase_node = loop.create_node(
                phase_class,
                name=f"{phase_name}",
                assistant_role_name=phase_config.get('assistant_role_name', 'Assistant'),
                instructor_role_name=phase_config.get('user_role_name', 'Instructor'),
                assistant_instructions=phase_config.get('assistant_role_prompt', ''),
                instructor_instructions=phase_config.get('user_role_prompt', ''),
                phase_instructions=phase_config.get('phase_prompt', []),
                model=self._model,
                memory=self._memory,
                max_turns=max_turn_step,
                reflect_roles=self._reflect_roles if need_reflect else None
            )

            edge_switch_to_phase = loop.create_edge(
                sender=round_control_switch,
                receiver=phase_node,
                keys={}
            )
            round_control_switch.condition_binding(
                condition=round_control_switch_condition_factory(index,max_index),
                out_edge=edge_switch_to_phase
            )

            loop.edge_to_controller(
                sender=phase_node,
                keys={}
            )
       
        loop.edge_from_controller(
            receiver=round_control_switch,
            keys={}
        )

        # entry → pre_loop_action
        self.edge_from_entry(
            receiver=pre_loop_action,
            keys={}
        )

        # pre_loop_action → loop
        self.create_edge(
            sender=pre_loop_action,
            receiver=loop,
            keys={}
        )

        # loop → post_loop_action
        self.create_edge(
            sender=loop,
            receiver=post_loop_action,
            keys={}
        )

        # post_loop_action → exit
        self.edge_to_exit(
            sender=post_loop_action,
            keys={}
        )

        super().build()



class ArtComposedPhase(ComposedPhase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._pull_keys = {
            "task": "The task prompt for software development",
            "description": "The task description",
            "language": "The programming language",
            "codes": "The current source code files",
            "image_model": "The image generation model"
        }

        self._push_keys = {
            "codes": "The updated source code with integrated images",
            "images": "The generated image assets"
        }

        # Art phase does not need a special break condition, always executes all loops
        self._break_condition_func = lambda messages, attributes: False


class CodeCompleteAllComposedPhase(ComposedPhase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._pull_keys = {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "codes": "The current source code files",
            "directory": "The project directory path"
        }

        self._push_keys = {
            "codes": "The updated source code with completed implementations"
        }

        # Pre-processing: initialize Python file list and attempt counts
        def pre_loop_action(messages: dict, attributes: dict):
            directory = attributes.get("directory", "")
            if directory and os.path.exists(directory):
                pyfiles = [f for f in os.listdir(directory) if f.endswith(".py")]
            else:
                pyfiles = []

            num_tried = defaultdict(int)
            num_tried.update({filename: 0 for filename in pyfiles})

            # attributes["max_num_implement"] = 5
            attributes["pyfiles"] = pyfiles
            attributes["num_tried"] = num_tried

            return messages

        self._pre_loop_action_func = pre_loop_action

        # Break condition: interrupt when no unimplemented files remain
        def break_condition(messages: dict, attributes: dict):
            unimplemented_file = attributes.get("unimplemented_file", "")
            logger.debug("Phase break condition check: unimplemented_file=%s", unimplemented_file)
            return unimplemented_file == ""

        self._break_condition_func = break_condition


class CodeReviewComposedPhase(ComposedPhase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._pull_keys = {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "codes": "The current source code files",
            "code_manager": "The Object of Codes class",
            "images": "Incorporated image assets"
        }

        self._push_keys = {
            "codes": "The updated source code after code review"
        }

        # Pre-processing: initialize modification conclusion
        def pre_loop_action(messages: dict, attributes: dict):
            attributes["modification_conclusion"] = ""
            return messages

        self._pre_loop_action_func = pre_loop_action

        # Break condition: interrupt when modification conclusion contains completion info
        def break_condition(messages: dict, attributes: dict):
            modification_conclusion = attributes.get("modification_conclusion", "")
            return "Finished".lower() in modification_conclusion.lower()

        self._break_condition_func = break_condition


class HumanAgentInteractionComposedPhase(ComposedPhase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._pull_keys = {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "codes": "The current source code files"
        }

        self._push_keys = {
            "codes": "The updated source code after human review"
        }

        # Pre-processing: initialize modification conclusion and comments
        def pre_loop_action(messages: dict, attributes: dict):
            attributes["modification_conclusion"] = ""
            attributes["comments"] = ""
            return messages

        self._pre_loop_action_func = pre_loop_action

        # Break condition: interrupt when modification conclusion contains completion info or user enters "exit"
        def break_condition(messages: dict, attributes: dict):
            modification_conclusion = attributes.get("modification_conclusion", "")
            comments = attributes.get("comments", "")
            return ("Finished".lower() in modification_conclusion.lower() or
                    comments.lower() == "exit")

        self._break_condition_func = break_condition


class TestComposedPhase(ComposedPhase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._pull_keys = {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "codes": "The current source code files",
            "code_manager": "The Object of Codes class",
            "directory": "The project directory path",
            "test_reports": "The test reports generated after testing the code",
            "image_model": "The image generation model",
        }

        self._push_keys = {
            "codes": "The updated source code after testing and bug fixes"
        }

        # Break condition: interrupt when no bugs exist
        def break_condition(messages: dict, attributes: dict):
            exist_bugs_flag = attributes.get("exist_bugs_flag", True)
            if not exist_bugs_flag:
                logger.info("**[Test Info]**\n\nAI User (Software Test Engineer):\nTest Pass!\n")
            return not exist_bugs_flag

        self._break_condition_func = break_condition

