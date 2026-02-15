from applications.chatdev_lite.components.tools import (
    check_code_completeness_tool,
    run_tests_tool,
    save_requirements_tool,
    save_manual_tool,
    codes_check_and_processing_tool
)
from masfactory import Graph, Model, Memory, Node
from masfactory.components.composed_graph.instructor_assistant_graph import InstructorAssistantGraph
from masfactory.utils.hook import masf_hook
from typing import Callable, List

def concat_instructions(agent_instructions: list | str, phase_instructions: list | str):
    if isinstance(phase_instructions, list):
        phase_instructions = "\n".join(phase_instructions)
    if isinstance(agent_instructions, list):
        agent_instructions = "\n".join(agent_instructions)
    return phase_instructions + "\n" + agent_instructions

class LitePhase(Graph):
    """Lite Phase - Only contains InstructorAssistantGraph with tools"""
    def __init__(
        self,
        name: str,
        assistant_role_name: str,
        instructor_role_name: str,
        assistant_instructions: list | str,
        instructor_instructions: list | str,
        phase_instructions: list | str,
        model: Model,
        memory: Memory,
        max_turns: int = 10,
        tools: List[Callable] = None,
        tool_instruction: str = None,
    ):
        super().__init__(name)
        
        self._assistant_role_name = assistant_role_name
        self._instructor_role_name = instructor_role_name
        self._assistant_instructions = concat_instructions(assistant_instructions, phase_instructions)
        self._instructor_instructions = concat_instructions(instructor_instructions, phase_instructions)
        self._memory = memory
        self._model = model
        self._max_turns = max_turns
        self._tools = tools or []
        self._tool_instruction = tool_instruction
        
        self._pull_keys = {}
        self._push_keys = {}

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        assert self._pull_keys is not None, "pull_keys must be provided"
        assert self._push_keys is not None, "push_keys must be provided"

        if self._tool_instruction:
            if isinstance(self._assistant_instructions, str):
                self._assistant_instructions = self._tool_instruction + self._assistant_instructions
            else:
                self._assistant_instructions = self._tool_instruction + "\n".join(self._assistant_instructions)

        role_playing = self.create_node(
            InstructorAssistantGraph,
            name=f"{self._name}_role_playing",
            instructor_role_name=self._instructor_role_name,
            instructor_instructions=self._instructor_instructions,
            assistant_role_name=self._assistant_role_name,
            assistant_instructions=self._assistant_instructions,
            phase_instructions="",
            instructor_memories=[self._memory],
            assistant_memories=[self._memory],
            model=self._model,
            max_turns=2 * self._max_turns - 1,
            assistant_tools=self._tools,
            pull_keys=self._pull_keys,
            push_keys=self._push_keys,
            instructor_first=False
        )
        self.edge_from_entry(receiver=role_playing, keys={})
        self.edge_to_exit(sender=role_playing, keys={})
        super().build()

codes_keys_description = [{
    "filename": "the lowercase file name including the file extension",
    "language": "the programming language",
    "docstring": "documentation string",
    "code": "the original code"
}]


class DemandAnalysisPhase(LitePhase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pull_keys = {
            "task": "The task prompt for software development",
            "description": "The task description",
            "chatdev_prompt": "The background prompt for ChatDev"
        }
        self._push_keys = {
            "modality": "The product modality (application/website/game/tool/library)"
        }


class LanguageChoosePhase(LitePhase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pull_keys = {
            "task": "The task prompt for software development",
            "description": "The task description",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "chatdev_prompt": "The background prompt for ChatDev"
        }
        self._push_keys = {
            "language": "The programming language (e.g., Python, JavaScript, Java)"
        }


class CodingPhase(LitePhase):
    def __init__(self, *args, **kwargs):
        tools = [codes_check_and_processing_tool, check_code_completeness_tool]     
        super().__init__(*args, **kwargs, tools=tools)   
        self._pull_keys = {
            "task": "The task prompt for software development",
            "description": "The task description",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "chatdev_prompt": "The background prompt for ChatDev",
            "gui": "GUI framework requirements",
            "unimplemented_file": "",
        }
        self._push_keys = {
            "codes": codes_keys_description,
            "unimplemented_file": "The filename of the unimplemented file (if any)"
        }


class CodeCompletePhase(LitePhase):
    def __init__(self, *args, **kwargs):
        tools = [codes_check_and_processing_tool]
        super().__init__(*args, **kwargs, tools=tools)
        self._pull_keys = {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "codes": "The current source code files",
            "chatdev_prompt": "The background prompt for ChatDev",
            "unimplemented_file": "",
        }
        self._push_keys = {
            "codes": codes_keys_description
        }


class CodeReviewPhase(LitePhase):
    """
    Merged code review phase combining comment generation and modification.
    Programmer reviews code with CTO guidance, fixes issues if found.
    """
    def __init__(self, *args, **kwargs):
        tools = [codes_check_and_processing_tool]
        super().__init__(*args, **kwargs, tools=tools)
        self._pull_keys = {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "codes": "The current source code files",
            "chatdev_prompt": "The background prompt for ChatDev",
            "unimplemented_file": "",
        }
        self._push_keys = {
            "codes": codes_keys_description,
            "review_conclusion": "Review conclusion: 'Finished' if code passes, or description of remaining issues"
        }


class TestErrorSummaryPhase(LitePhase):
    def __init__(self, *args, **kwargs):
        tools = [run_tests_tool]        
        super().__init__(*args, **kwargs, tools=tools)
        self._pull_keys = {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "codes": "The current source code files",
            "chatdev_prompt": "The background prompt for ChatDev",
            "test_reports": "Detailed test reports",
            "directory": "The working directory",
            "incorporated_images": "The list of incorporated images",
            "proposed_images": "The list of proposed images",
            "image_model": "The image generation model",
        }
        self._push_keys = {
            "error_summary": "Summary of errors found",
            "test_reports": "Detailed test reports",
        }

class TestModificationPhase(LitePhase):
    def __init__(self, *args, **kwargs):
        tools = [codes_check_and_processing_tool]      
        super().__init__(*args, **kwargs, tools=tools)
        self._pull_keys = {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "test_reports": "Test execution reports",
            "error_summary": "Summary of errors to fix",
            "codes": "The current source code files",
            "chatdev_prompt": "The background prompt for ChatDev"
        }
        self._push_keys = {
            "modification_conclusion": "Fix status (Finished!/Need improve)",
            "codes": codes_keys_description
        }



class EnvironmentDocPhase(LitePhase):
    def __init__(self, *args, **kwargs):
        tools = [save_requirements_tool]       
        super().__init__(*args, **kwargs, tools=tools)
        self._pull_keys = {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "codes": "The current source code files",
            "chatdev_prompt": "The background prompt for ChatDev"
        }
        self._push_keys = {
            "requirements": "The project dependency requirements"
        }


class ManualPhase(LitePhase):
    def __init__(self, *args, **kwargs):
        tools = [save_manual_tool]        
        super().__init__(*args, **kwargs, tools=tools)
        self._pull_keys = {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "codes": "The current source code files",
            "requirements": "The project dependency requirements",
            "chatdev_prompt": "The background prompt for ChatDev"
        }
        self._push_keys = {
            "manual": "The user manual documentation"
        }