"""ChatDev Lite - Simplified implementation using InstructorAssistantGraph

A cleaner, more maintainable version of ChatDev that follows the paper's structure
while using MASFactory's InstructorAssistantGraph for phase implementation.
"""

import os
import sys
import argparse
import logging
import time

from masfactory import RootGraph, OpenAIModel, CustomNode, VectorMemory, LogicSwitch, Loop
from masfactory.utils.embedding import SimpleEmbedder
from applications.chatdev_lite.workflow.utils import get_config, get_attributes
from applications.chatdev_lite.workflow.handlers import pre_processing, post_processing 


# Import LitePhase classes
from applications.chatdev_lite.components.lite_phase import (
    DemandAnalysisPhase,
    LanguageChoosePhase,
    CodingPhase,
    CodeCompletePhase,
    CodeReviewPhase,
    TestErrorSummaryPhase,
    TestModificationPhase,
    EnvironmentDocPhase,
    ManualPhase
)

DEFAULT_OPENAI_BASE_URL = ""
DEFAULT_OPENAI_API_KEY = "sk-"


parser = argparse.ArgumentParser(description='ChatDev command-line arguments')
parser.add_argument('--org', type=str, default="DefaultOrganization", help="Organization name; software will be generated in WareHouse/name_org_timestamp directory")
parser.add_argument('--task', type=str, default="Develop a basic Gomoku game.", help="Task prompt for software development")
parser.add_argument('--name', type=str, default="Gomoku", help="Software name; software will be generated in WareHouse/name_org_timestamp directory")
parser.add_argument('--model', type=str, default="gpt-4o-mini", help="Model name, default is gpt-4o-mini, follows OpenAI interface. If using base_url, follows base_url provider")
parser.add_argument('--api_key', type=str, default=None, help="API key, default is empty, uses environment variable OPENAI_API_KEY")
parser.add_argument('--base_url', type=str, default=None, help="API base URL, default is empty, uses environment variable BASE_URL")
args = parser.parse_args()

args.api_key = args.api_key if args.api_key else os.getenv("OPENAI_API_KEY", DEFAULT_OPENAI_API_KEY)  # Use os.getenv() to get environment variable
args.base_url = args.base_url if args.base_url else os.getenv("BASE_URL", DEFAULT_OPENAI_BASE_URL)

config_path, config_phase_path, config_role_path = get_config()
env_keys, environments = get_attributes(args)

logging.basicConfig(filename=environments['log_filepath'], level=logging.INFO,
                    format='[%(asctime)s %(levelname)s] %(message)s',
                    datefmt='%Y-%d-%m %H:%M:%S', encoding="utf-8")

model: OpenAIModel = OpenAIModel(model_name=args.model, api_key=args.api_key, base_url=args.base_url)

chatdev_lite: RootGraph = RootGraph(name="chatdev_lite", attributes=environments)

# Create embedding function for memory
embedder = SimpleEmbedder(vocab_size=10000)
embedding_function = embedder.get_embedding_function()

# ----------------------------------------
#          Pre Processing
# ----------------------------------------
pre_processing_node = chatdev_lite.create_node(CustomNode, "pre_processing")
pre_processing_node.set_forward(pre_processing)
chatdev_lite.edge_from_entry(receiver=pre_processing_node, keys={})

# ----------------------------------------
#          Main Chat Chain
# ----------------------------------------

# 1. Demand Analysis Phase
demand_analysis = chatdev_lite.create_node(
    DemandAnalysisPhase,
    name="demand_analysis_phase",
    assistant_role_name="Chief Product Officer",
    instructor_role_name="Chief Executive Officer",
    assistant_instructions=environments["config_role"]["Chief Product Officer"],
    instructor_instructions=environments["config_role"]["Chief Executive Officer"],
    phase_instructions=environments["config_phase"]["DemandAnalysis"]["phase_prompt"],
    model=model,
    memory=VectorMemory(embedding_function=embedding_function, context_label="DEMAND_ANALYSIS_MEMORY"),
    max_turns=3
)

chatdev_lite.create_edge(
    sender=pre_processing_node,
    receiver=demand_analysis,
    keys={}
)

# 2. Language Choose Phase
language_choose = chatdev_lite.create_node(
    LanguageChoosePhase,
    name="language_choose_phase",
    assistant_role_name="Chief Technology Officer",
    instructor_role_name="Chief Executive Officer",
    assistant_instructions=environments["config_role"]["Chief Technology Officer"],
    instructor_instructions=environments["config_role"]["Chief Executive Officer"],
    phase_instructions=environments["config_phase"]["LanguageChoose"]["phase_prompt"],
    model=model,
    memory=VectorMemory(embedding_function=embedding_function, context_label="LANGUAGE_CHOOSE_MEMORY"),
    max_turns=3
)

chatdev_lite.create_edge(
    sender=demand_analysis,
    receiver=language_choose,
    keys={}
)

# 3. Coding Phase
coding = chatdev_lite.create_node(
    CodingPhase,
    name="coding_phase",
    assistant_role_name="Programmer",
    instructor_role_name="Chief Technology Officer",
    assistant_instructions=environments["config_role"]["Programmer"],
    instructor_instructions=environments["config_role"]["Chief Technology Officer"],
    phase_instructions=environments["config_phase"]["Coding"]["phase_prompt"],
    tool_instruction=environments["config_phase"]["Coding"]["tool_instruction"],
    model=model,
    memory=VectorMemory(embedding_function=embedding_function, context_label="CODING_MEMORY"),
    max_turns=1
)

chatdev_lite.create_edge(
    sender=language_choose,
    receiver=coding,
    keys={}
)

# Logic Switch
code_complete_switch = chatdev_lite.create_node(
    LogicSwitch,
    name="code_complete_switch",
)

chatdev_lite.create_edge(
    sender=coding,
    receiver=code_complete_switch,
    keys={}
)

# 4. Code Complete Phase
code_complete = chatdev_lite.create_node(
    CodeCompletePhase,
    name="code_complete_phase",
    assistant_role_name="Programmer",
    instructor_role_name="Chief Technology Officer",
    assistant_instructions=environments["config_role"]["Programmer"],
    instructor_instructions=environments["config_role"]["Chief Technology Officer"],
    phase_instructions=environments["config_phase"]["CodeComplete"]["phase_prompt"],
    tool_instruction=environments["config_phase"]["CodeComplete"]["tool_instruction"],
    model=model,
    memory=VectorMemory(embedding_function=embedding_function, context_label="CODE_COMPLETE_ALL_COMPOSED_MEMORY"),
    max_turns=3
)

# 5. Code Review Phase
code_review_phase = chatdev_lite.create_node(
    CodeReviewPhase,
    name="code_review_phase",
    assistant_role_name="Programmer",
    instructor_role_name="Chief Technology Officer",
    assistant_instructions=environments["config_role"]["Programmer"],
    instructor_instructions=environments["config_role"]["Chief Technology Officer"],
    phase_instructions=environments["config_phase"]["CodeReviewComment"]["phase_prompt"],
    tool_instruction=environments["config_phase"]["CodeReviewComment"]["tool_instruction"],
    model=model,
    memory=VectorMemory(embedding_function=embedding_function, context_label="CODE_REVIEW_COMPOSED_MEMORY"),
    max_turns=1
)
# True branch: →  CodeCompletePhase
switch_to_code_complete = chatdev_lite.create_edge(
    sender=code_complete_switch,
    receiver=code_complete,
    keys={},
)

# False branch: →  CodeReview
switch_to_code_review = chatdev_lite.create_edge(
    sender=code_complete_switch,
    receiver=code_review_phase,
    keys={}
)

code_complete_switch.condition_binding(
    condition=lambda message, attributes: attributes.get("unimplemented_file") not in (None, "", "None"),
    out_edge=switch_to_code_complete
)
code_complete_switch.condition_binding(
    condition=lambda message, attributes: attributes.get("unimplemented_file") in (None, "", "None"),
    out_edge=switch_to_code_review
)

# CodeComplete → CodeReview
chatdev_lite.create_edge(
    sender=code_complete,
    receiver=code_review_phase,
    keys={}
)
# 6. Test Loop
def test_terminate(messages: dict, attributes: dict) -> bool:
    """Terminate when no bugs exist"""
    exist_bugs = attributes.get("exist_bugs_flag", True)
    return not exist_bugs

test_loop = chatdev_lite.create_node(
    Loop,
    name="test_loop",
    max_iterations=3,
    terminate_condition_function=test_terminate
)

test_error_summary = test_loop.create_node(
    TestErrorSummaryPhase,
    name="test_error_summary_phase",
    assistant_role_name="Programmer",
    instructor_role_name="Software Test Engineer",
    assistant_instructions=environments["config_role"]["Programmer"],
    instructor_instructions=environments["config_role"]["Software Test Engineer"],
    phase_instructions=environments["config_phase"]["TestErrorSummary"]["phase_prompt"],
    tool_instruction=environments["config_phase"]["TestErrorSummary"]["tool_instruction"],
    model=model,
    memory=VectorMemory(embedding_function=embedding_function, context_label="TEST_ERROR_MEMORY"),
    max_turns=1
)

test_modification = test_loop.create_node(
    TestModificationPhase,
    name="test_modification_phase",
    assistant_role_name="Programmer",
    instructor_role_name="Chief Technology Officer",
    assistant_instructions=environments["config_role"]["Programmer"],
    instructor_instructions=environments["config_role"]["Chief Technology Officer"],
    phase_instructions=environments["config_phase"]["TestModification"]["phase_prompt"],
    tool_instruction=environments["config_phase"]["TestModification"]["tool_instruction"],
    model=model,
    memory=VectorMemory(embedding_function=embedding_function, context_label="TEST_MODIFICATION_MEMORY"),
    max_turns=1
)

test_loop.edge_from_controller(receiver=test_error_summary, keys={})
test_loop.create_edge(
    sender=test_error_summary,
    receiver=test_modification,
    keys={}
)
test_loop.edge_to_controller(sender=test_modification, keys={})

chatdev_lite.create_edge(
    sender=code_review_phase,
    receiver=test_loop,
    keys={}
)

# 7. Environment Documentation Phase
environment_doc = chatdev_lite.create_node(
    EnvironmentDocPhase,
    name="environment_doc_phase",
    assistant_role_name="Programmer",
    instructor_role_name="Chief Technology Officer",
    assistant_instructions=environments["config_role"]["Programmer"],
    instructor_instructions=environments["config_role"]["Chief Technology Officer"],
    phase_instructions=environments["config_phase"]["EnvironmentDoc"]["phase_prompt"],
    tool_instruction=environments["config_phase"]["EnvironmentDoc"]["tool_instruction"],
    model=model,
    memory=VectorMemory(embedding_function=embedding_function, context_label="ENVIRONMENT_DOC_MEMORY"),
    max_turns=1
)

chatdev_lite.create_edge(
    sender=test_loop,
    receiver=environment_doc,
    keys={}
)

# 8. Manual Phase
manual = chatdev_lite.create_node(
    ManualPhase,
    name="manual_phase",
    assistant_role_name="Chief Product Officer",
    instructor_role_name="Chief Executive Officer",
    assistant_instructions=environments["config_role"]["Chief Product Officer"],
    instructor_instructions=environments["config_role"]["Chief Executive Officer"],
    phase_instructions=environments["config_phase"]["Manual"]["phase_prompt"],
    tool_instruction=environments["config_phase"]["Manual"]["tool_instruction"],
    model=model,
    memory=VectorMemory(embedding_function=embedding_function, context_label="MANUAL_MEMORY"),
    max_turns=1
)

chatdev_lite.create_edge(
    sender=environment_doc,
    receiver=manual,
    keys={}
)

# ----------------------------------------
#          Post Processing
# ----------------------------------------
post_processing_node = chatdev_lite.create_node(CustomNode, "post_processing")
post_processing_node.set_forward(post_processing)

chatdev_lite.create_edge(
    sender=manual,
    receiver=post_processing_node,
    keys={}
)


chatdev_lite.edge_to_exit(sender=post_processing_node, keys={})

chatdev_lite.build()
chatdev_lite.invoke(input={}, attributes=environments)
