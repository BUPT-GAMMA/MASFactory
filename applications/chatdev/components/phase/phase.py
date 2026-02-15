from masfactory import Graph, Model, Memory, CustomNode, LogicSwitch, Node, masf_hook
from masfactory.components.composed_graph.instructor_assistant_graph import InstructorAssistantGraph
import logging
from applications.chatdev.components.phase.handlers import (
    get_proposed_images_from_message,
    codes_check_and_processing,
    check_un_implemented_file,
    code_review_human_interaction,
    check_bugs_and_get_error_summary,
    requirements_update_and_rewrite,
    manual_update_and_rewrite,
)

logger = logging.getLogger(__name__)

def concat_instructions(agent_instructions: list | str, phase_instructions: list | str):
    if isinstance(phase_instructions, list):
        phase_instructions = "\n".join(phase_instructions)
    if isinstance(agent_instructions, list):
        agent_instructions = "\n".join(agent_instructions)
    return phase_instructions + "\n" + agent_instructions

class Phase(Graph):
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
        reflect_roles: dict | None = None,        
    ):

        super().__init__(name)
        assert max_turns >=1 and max_turns <= 100, "max_turns must be in [1, 100]"
        self._assistant_role_name = assistant_role_name
        self._instructor_role_name = instructor_role_name
        self._assistant_instructions = concat_instructions(assistant_instructions, phase_instructions)
        self._instructor_instructions = concat_instructions(instructor_instructions, phase_instructions)
        self._memory = memory
        self._model = model
        self._need_reflect = reflect_roles is not None
        self._phase_instructions = phase_instructions
        self._ceo_instructions = reflect_roles["ceo"] if self._need_reflect else None
        self._counselor_instructions = reflect_roles["counselor"] if self._need_reflect else None
        self._max_turns = max_turns
        self._reflect_instructions = "Here is a conversation between two roles:{conversations} {question}"
        
        self._phase_reflection_question = ""
        self._allow_skip_phase = False
        self._pre_action_func = None
        self._post_action_func = None
        self._agent_pull_keys = None
        self._agent_push_keys = None
    @masf_hook(Node.Hook.BUILD)
    def build(self):
        assert self._pull_keys is not None, "pull_keys must be provided"
        assert self._push_keys is not None, "push_keys must be provided"
        if self._agent_pull_keys == None:
            self._agent_pull_keys = self._pull_keys
        if self._agent_push_keys == None:
            self._agent_push_keys = self._push_keys
        self._attributes_store = {**self._attributes_store,**self._pull_keys}
        def role_playing_terminate_condition_function(message: dict, attributes: dict[str, object],controller:Node) -> bool:
            discussion_finished = attributes.get("discussion_finished", False)
            if discussion_finished in ["False", "false", "FALSE", False]:
                logger.debug("%s discussion_finished is False; continue role playing", controller.name)
                return False
            logger.debug("%s discussion_finished is True; terminate role playing", controller.name)
            return True
        pre_action = self.create_node(
            CustomNode,
            name=self._name + "_pre_action_custom_node",
            forward=self._pre_action_func
        )
        
        post_action = self.create_node(
            CustomNode,
            name=self._name + "_after_phase_action",
            forward=self._post_action_func
        )
        role_playing = self.create_node(
            InstructorAssistantGraph,
            name=self._name + "_role_playing_graph",
            instructor_role_name=self._instructor_role_name,
            instructor_instructions=self._instructor_instructions,
            assistant_role_name=self._assistant_role_name,
            assistant_instructions=self._assistant_instructions,
            phase_instructions=self._phase_instructions,
            instructor_memories=[self._memory],
            assistant_memories=[self._memory],
            model=self._model,
            max_turns=2 * self._max_turns - 1,
            terminate_condition_function=role_playing_terminate_condition_function,
            pull_keys=self._agent_pull_keys,
            push_keys=self._agent_push_keys
        )
        # reflection
        if self._need_reflect:
            reflection_placeholders= {
                "conversations":"",
                "question":"",
            }
            def reflection_set_inputs(IAGraph:InstructorAssistantGraph,result:dict,input:dict) -> str:
                conversations = []
                instructor_chat_history = IAGraph.instructor_chat_history.get_messages(top_k=10000)
                assistant_chat_history = IAGraph.assistant_chat_history.get_messages(top_k=10000)
                chat_history = instructor_chat_history if len(instructor_chat_history) > len(assistant_chat_history) else assistant_chat_history
                assistant_role_name = self._instructor_role_name if len(instructor_chat_history) > len(assistant_chat_history) else self._assistant_role_name
                user_role_name = self._instructor_role_name if len(instructor_chat_history) <= len(assistant_chat_history) else self._assistant_role_name

                for message in chat_history:
                    if message["role"] == "assistant":
                        role_name = assistant_role_name
                    else:
                        role_name = user_role_name
                    # Format each message as "role_name: content".
                    conversations.append(f"{role_name}: {message['content']}")
                conversations = "\n".join(conversations)
                
                reflection_placeholders["conversations"] = conversations
                reflection_placeholders["question"] = self._phase_reflection_question
                if "discussion_finished" in IAGraph.attributes:
                    reflection_placeholders["discussion_finished"] = IAGraph.attributes["discussion_finished"]
                return result
            reflection_setting_action = self.create_node(
                CustomNode,
                name=self._name + "_reflection_setting_action",
                forward=lambda input, attributes : reflection_placeholders
            )
            reflection = self.create_node(
                InstructorAssistantGraph,
                name=self._name + "_reflection_graph",
                instructor_role_name="Counselor",
                instructor_instructions=self._counselor_instructions,
                assistant_role_name="Chief Executive Officer",
                assistant_instructions=self._ceo_instructions,
                phase_instructions=self._reflect_instructions,
                instructor_memories=[self._memory],
                assistant_memories=[self._memory],
                model=self._model,
                max_turns=1,
                terminate_condition_function=role_playing_terminate_condition_function,
                pull_keys=self._agent_pull_keys,
                push_keys=self._agent_push_keys
            )
            
            role_playing.hooks.register(Node.Hook.FORWARD.AFTER, reflection_set_inputs)
            self.create_edge(
                sender=role_playing,
                receiver=reflection_setting_action,
                keys={}
            )
            self.create_edge(
                sender=reflection_setting_action,
                receiver=reflection,
                keys={"conversations":"The conversations between two roles","question":"The question to be solved"}
            )
            self.create_edge(
                sender=reflection,
                receiver=post_action,
                keys={}
            )
        else:
            self.create_edge(
                sender=role_playing,
                receiver=post_action,
                keys={}
            )
        if self._allow_skip_phase:   
            skip:LogicSwitch = self.create_node(
                LogicSwitch,
                name=self._name + "_skip_logic_switch",
            )
            self.create_edge(
                sender=pre_action,
                receiver=skip,
                keys={"skip_flag":"True or False"}
            )
            continue_edge = self.create_edge(
                sender=skip,
                receiver=role_playing,
                keys={}
            )
            skip_edge = self.edge_to_exit(
                sender=skip,
                keys={}
            )
            skip.condition_binding(
                condition=lambda message, attributes: message.get("skip_flag", False) == True ,
                out_edge=skip_edge
            )
            skip.condition_binding(
                condition=lambda message, attributes: message.get("skip_flag", False) == False,
                out_edge=continue_edge
            )
             
        else:
            self.create_edge(
                sender=pre_action,
                receiver=role_playing,
                keys={} 
            )
        self.edge_to_exit(
            sender=post_action,
            keys={}
        )

        self.edge_from_entry(
            receiver=pre_action,
            keys={}
        )
        super().build()

codes_keys_description = [{
    "filename":"the lowercase file name including the file extension",
    "language":"the programming language",
    "docstring":"a string literal specified in source code that is used to document a specific segment of code",
    "code":"the original code"
},
{
    "filename":"the lowercase file name including the file extension",
    "language":"the programming language",
    "docstring":"a string literal specified in source code that is used to document a specific segment of code",
    "code":"the original code"
}
]
conclusion_key_description = {
    "discussion_finished": "True or False. True if the your discussion has reached a concreted conclusion, False otherwise. And if this flag is False."
}
conclusion_key_default = {
    "discussion_finished":False
}

class DemandAnalysisPhase(Phase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pull_keys = {
            "task": "The task prompt for software development",
            "description": "The task description",
            "chatdev_prompt": "The background prompt for ChatDev",
            "discussion_opinion": "No opinions yet.",
            # **conclusion_key_default
        }
        self._push_keys = {
            "discussion_opinion":"Your opinion on the demand analysis. You can discuss which modality could be used here.",
            "modality": "The product modality determined from demand analysis. If you not sure about the modality yet, you can make a empty str in this field.",
            # **conclusion_key_description
        }
        self._phase_reflection_question = """Answer their final product modality in the discussion without any other words. """
        self._agent_pull_keys = {**self._pull_keys, **conclusion_key_default}
        self._agent_push_keys = {**self._push_keys, **conclusion_key_description}
        self.attributes["discussion_finished"] = False

class LanguageChoosePhase(Phase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pull_keys = {
            "task": "The task prompt for software development",
            "description": "The task description",
            "modality": "The product modality (e.g., application, website, game)",
            "ideas": "Creative ideas for the software",
            "chatdev_prompt": "The background prompt for ChatDev",
            "discussion_opinion": "No opinions yet.",
            # **conclusion_key_default
        }
        self._push_keys = {
            "discussion_opinion":"Your opinion on the language choose. You can discuss which language could be used here.",
            "language": "The programming language chosen for development",
            # **conclusion_key_description
        }
        self._phase_reflection_question = """Conclude the programming language being discussed for software development, in the format: "*" where '*' represents a programming language." """
        self._agent_pull_keys = {**self._pull_keys, **conclusion_key_default}
        self._agent_push_keys = {**self._push_keys, **conclusion_key_description}
        self.attributes["discussion_finished"] = False

class CodingPhase(Phase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pull_keys = {
            "task": "The task prompt for software development",
            "description": "The task description",
            "modality": "The product modality", 
            "ideas": "Creative ideas for the software",
            "language": "The programming language for development",
            "chatdev_prompt": "The background prompt for ChatDev",
            "git_management": False,
            "gui": "GUI framework requirements",
            "code_manager": "The Object of Codes class",
        }
        self._push_keys = {
            "codes": codes_keys_description 
        }
        self._post_action_func = codes_check_and_processing("Finish Coding!")

class ArtDesignPhase(Phase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pull_keys = {
            "task": "The task prompt for software development",
            "description": "The task description",
            "language": "The programming language",
            "codes": "The current source code files", 
            "image_model": "The image generation model",
            "chatdev_prompt": "The background prompt for ChatDev",
        }
        self._agent_pull_keys= {
            "task": "The task prompt for software development",
            "description": "The task description",
            "language": "The programming language",
            "codes": "The current source code files",
            "chatdev_prompt": "The background prompt for ChatDev",
            "proposed_images": "The proposed image assets"
        }
        self._agent_push_keys = {
            "images": [{
                "image_name": "The filename of the image. Should be end with .png, e.g., button_1.png",
                "description": "The detailed description of the independent elements in the image."
            }]
        }
        self._push_keys = {
            "images": [{
                "image_name": "The filename of the image. Should be end with .png, e.g., button_1.png",
                "description": "The detailed description of the independent elements in the image."
            }],
            "proposed_images": "The proposed image assets",
            "incorporated_images": "The incorporated image assets"
        }
        self._post_action_func = get_proposed_images_from_message


class ArtIntegrationPhase(Phase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pull_keys = {
            "task": "The task prompt for software development",
            "language": "The programming language",
            "codes": "The current source code files",
            "images": "The image assets to integrate",
            "chatdev_prompt": "The background prompt for ChatDev",
        }
        self._push_keys = {
            "codes": codes_keys_description
        }
        self._post_action_func = codes_check_and_processing("Finish Art Integration")


class CodeCompletePhase(Phase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pull_keys = {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "codes": "The current source code files",
            "chatdev_prompt": "The background prompt for ChatDev",
            "unimplemented_file": "",
            "cycle_index": 0,
            "git_management": False,
        }
        self._push_keys = {
            "codes": codes_keys_description
        }
        self._pre_action_func = check_un_implemented_file
        self._post_action_func = codes_check_and_processing("Code Complete # {} Finished.", "cycle_index")


class CodeReviewCommentPhase(Phase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pull_keys = {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "codes": "The current source code files",
            "images": "Incorporated image assets",
            "cycle_index": 0,
            "chatdev_prompt": "The background prompt for ChatDev",
        }
        self._push_keys = {
            "review_comments": "Code review comments and suggestions. If no comment, the value should be \"Finished\"."
        }


class CodeReviewModificationPhase(Phase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pull_keys = {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "codes": "The current source code files",
            "code_manager": "The Object of Codes class",
            "review_comments": "Code review comments to address",
            "chatdev_prompt": "The background prompt for ChatDev",
            "cycle_index": 0,
            "git_management": False,
        }
        self._push_keys = {
            "codes": codes_keys_description,
            "modification_conclusion": "The conclusion of the review modification. e.g. Finished! or Still need to improve. "
        }
        self._post_action_func = codes_check_and_processing("Review # {} Finished.", "cycle_index")


class CodeReviewHumanPhase(Phase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pull_keys = {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "codes": "The current source code files",
            "chatdev_prompt": "The background prompt for ChatDev",
            "cycle_index": 0,
            "git_management": False,
        }
        self._agent_pull_keys = {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "codes": "The current source code files",
            "chatdev_prompt": "The background prompt for ChatDev",
            "cycle_index": 0,
            "comments": "Code review comments to address"
        }
        self._push_keys = {
            "codes": "The updated source code after human review"
        }
        self._allow_skip_phase = True
        self._pre_action_func = code_review_human_interaction
        self._post_action_func = codes_check_and_processing("Human Review # {} Finished.", "cycle_index")

class TestErrorSummaryPhase(Phase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._allow_skip_phase = True
        self._pull_keys = {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "codes": "The current source code files",
            "code_manager": "The Object of Codes class",
            "chatdev_prompt": "The background prompt for ChatDev",
            "directory": "The working directory",
            "incorporated_images": "",
            "proposed_images":"",
            "image_model": "The image generation model",
        }
        self._agent_pull_keys = {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "codes": "The current source code files",
            "chatdev_prompt": "The background prompt for ChatDev",
            "test_reports": "Test execution reports",
            "exist_bugs_flag": "Flag indicating if bugs exist"
        }
        self._agent_push_keys = {
            "error_summary": "Summary of errors found in test reports"
        }
        self._push_keys = {
            "error_summary": "Summary of errors found during testing",
            "test_reports": "Detailed test reports"
        }
        self.attributes["test_reports"] = ""
        self._pre_action_func = check_bugs_and_get_error_summary


class TestModificationPhase(Phase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pull_keys = {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "test_reports": "Test execution reports",
            "error_summary": "Summary of errors to fix",
            "chatdev_prompt": "The background prompt for ChatDev",
            "codes": "The current source code files",
            "code_manager": "The Object of Codes class",
            "directory": "The working directory",
            "cycle_index": 0,
            "git_management": False,
            # **conclusion_key_default   
        }
        self._push_keys = {
            "codes": codes_keys_description,
            "modification_conclusion": "The conclusion of the review modification. e.g. Finished! or Still need to improve. ",
            # **conclusion_key_description
        }
        self._agent_pull_keys = {**self._pull_keys, **conclusion_key_default}
        self._agent_push_keys = {**self._push_keys, **conclusion_key_description}
        self._post_action_func = codes_check_and_processing("Test # {} Finished.", "cycle_index")

class EnvironmentDocPhase(Phase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pull_keys = {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "codes": "The current source code files",
            "chatdev_prompt": "The background prompt for ChatDev",
            "requirement_manager": "The Object of Documents class",
        }
        self._agent_pull_keys = {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "codes": "The current source code files",
            "chatdev_prompt": "The background prompt for ChatDev",
        }
        self._push_keys = {
            "requirements": "The project dependency requirements",
            # **conclusion_key_description
        }
        self._phase_reflection_question = """According to the codes and file format listed above, write a requirements.txt file to specify the dependencies or packages required for the project to run properly." """
        self._agent_pull_keys = {**self._pull_keys, **conclusion_key_default}
        self._agent_push_keys = {**self._push_keys, **conclusion_key_description}
        self.attributes["discussion_finished"] = False
        self._post_action_func = requirements_update_and_rewrite


class ManualPhase(Phase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pull_keys = {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "codes": "The current source code files",
            "requirements": "The project dependency requirements",
            "chatdev_prompt": "The background prompt for ChatDev",
            "manual_manager": "The Object of Documents class",
        }
        self._agent_pull_keys= {
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "ideas": "Creative ideas for the software",
            "language": "The programming language",
            "codes": "The current source code files",
            "requirements": "The project dependency requirements",
            "chatdev_prompt": "The background prompt for ChatDev",
        }
        self._push_keys = {
            "manual": "The user manual documentation"
        }
        self._post_action_func = manual_update_and_rewrite
