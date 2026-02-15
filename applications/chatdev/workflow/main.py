import argparse
import logging
import os


from masfactory import RootGraph, OpenAIModel, CustomNode, VectorMemory
from masfactory.utils.embedding import SimpleEmbedder
from applications.chatdev.components.phase.phase import DemandAnalysisPhase, LanguageChoosePhase, CodingPhase, CodeCompletePhase, CodeReviewCommentPhase, CodeReviewModificationPhase, TestErrorSummaryPhase, TestModificationPhase, EnvironmentDocPhase, ManualPhase
from applications.chatdev.components.composed_phase import CodeCompleteAllComposedPhase, CodeReviewComposedPhase, TestComposedPhase
from applications.chatdev.workflow.utils import get_config, get_attributes
from applications.chatdev.workflow.handlers import pre_processing, post_processing 

parser = argparse.ArgumentParser(description='ChatDev command-line arguments')
parser.add_argument('--org', type=str, default="DefaultOrganization", help="Organization name; software will be generated in WareHouse/name_org_timestamp directory")
parser.add_argument('--task', type=str, default="Develop a basic Gomoku game.", help="Task prompt for software development")
parser.add_argument('--name', type=str, default="Gomoku", help="Software name; software will be generated in WareHouse/name_org_timestamp directory")
parser.add_argument('--model', type=str, default="gpt-4o-mini", help="Model name, default is gpt-4o-mini, follows OpenAI interface. If using base_url, follows base_url provider")
parser.add_argument('--api_key', type=str, default=None, help="API key, default is empty, uses environment variable OPENAI_API_KEY")
parser.add_argument('--base_url', type=str, default=None, help="API base URL, default is empty, uses environment variable BASE_URL")
args = parser.parse_args()

args.api_key = args.api_key if args.api_key else os.getenv("OPENAI_API_KEY")  # Use os.getenv() to get environment variable
args.base_url = args.base_url if args.base_url else os.getenv("BASE_URL")

config_path, config_phase_path, config_role_path = get_config()
env_keys, environments = get_attributes(args)

logging.basicConfig(filename=environments['log_filepath'], level=logging.INFO,
                    format='[%(asctime)s %(levelname)s] %(message)s',
                    datefmt='%Y-%d-%m %H:%M:%S', encoding="utf-8")


# Create model adapter
model: OpenAIModel = OpenAIModel(model_name=args.model, api_key=args.api_key, base_url=args.base_url)
# Create root graph
chatdev: RootGraph = RootGraph(name="chatdev", attributes=environments)

# ----------------------------------------
#          Pre Processing
# ----------------------------------------
pre_processing_phase: CustomNode = chatdev.create_node(
        CustomNode,
        "pre_processing_phase",
    )

chatdev.edge_from_entry(
    receiver=pre_processing_phase,
    keys={}
)
# Set forward callback
pre_processing_phase.set_forward(pre_processing)

# # ----------------------------------------
# #          Chat Chain
# # ----------------------------------------
# Create SimpleEmbedder instance and get embedding function
embedder = SimpleEmbedder(vocab_size=10000)
embedding_function = embedder.get_embedding_function()

demand_analysis_phase : DemandAnalysisPhase = chatdev.create_node(
    DemandAnalysisPhase,
    name="demand_analysis_phase",
    assistant_role_name="Chief Product Officer",
    instructor_role_name="Chief Executive Officer",
    assistant_instructions=environments["config_role"]["Chief Product Officer"],
    instructor_instructions=environments["config_role"]["Chief Executive Officer"],
    phase_instructions=environments["config_phase"]['DemandAnalysis']['phase_prompt'],
    model=model,
    memory=VectorMemory(embedding_function=embedding_function, context_label="DEMAND_ANALYSIS_MEMORY"),
    max_turns=10,
    reflect_roles = {"ceo": environments["config_role"]["Chief Product Officer"], "counselor": environments["config_role"]["Chief Executive Officer"]},
)

chatdev.create_edge(
    sender=pre_processing_phase,
    receiver=demand_analysis_phase,
    keys={} 
)

language_choose_phase : LanguageChoosePhase = chatdev.create_node(
    LanguageChoosePhase,
    name="language_choose_phase",
    assistant_role_name="Chief Technology Officer",
    instructor_role_name="Chief Executive Officer",
    assistant_instructions=environments["config_role"]["Chief Technology Officer"],
    instructor_instructions=environments["config_role"]["Chief Executive Officer"],
    phase_instructions=environments["config_phase"]['LanguageChoose']['phase_prompt'],
    model=model,
    memory=VectorMemory(embedding_function=embedding_function, context_label="LANGUAGE_CHOOSE_MEMORY"),
    max_turns=10,
    reflect_roles = {"ceo": environments["config_role"]["Chief Technology Officer"], "counselor": environments["config_role"]["Chief Executive Officer"]},
)

chatdev.create_edge(
    sender=demand_analysis_phase,
    receiver=language_choose_phase,
    keys={}
)

coding_phase : CodingPhase = chatdev.create_node(
    CodingPhase,
    name="coding_phase",
    assistant_role_name="Programmer",
    instructor_role_name="Chief Technology Officer",
    assistant_instructions=environments["config_role"]["Programmer"],
    instructor_instructions=environments["config_role"]["Chief Technology Officer"],
    phase_instructions=environments["config_phase"]['Coding']['phase_prompt'],
    model=model,
    memory=VectorMemory(embedding_function=embedding_function, context_label="CODING_MEMORY"),
    max_turns=1,
)

chatdev.create_edge(
    sender=language_choose_phase,
    receiver=coding_phase,
    keys={}
)

code_complete_all_composed_phase : CodeCompleteAllComposedPhase = chatdev.create_node(
        CodeCompleteAllComposedPhase,
        name="code_complete_all_composed_phase",
        cycle_num=10,
        composition=[{
                "phase": "CodeComplete",
                "phaseType": "SimplePhase",
                "max_turn_step": 1,
                "need_reflect": "False"
            }],
        phase_classes={"CodeComplete": CodeCompletePhase},
        phase_configs={"CodeComplete": environments["config_phase"]['CodeComplete']},
        model=model,
        memory=VectorMemory(embedding_function=embedding_function, context_label="CODE_COMPLETE_ALL_COMPOSED_MEMORY"),
    )

chatdev.create_edge(
    sender=coding_phase,
    receiver=code_complete_all_composed_phase,
    keys={}
)

code_review_composed_phase : CodeReviewComposedPhase = chatdev.create_node(
        CodeReviewComposedPhase,
        name="code_review_composed_phase",
        cycle_num=3,
        composition=[{
                    "phase": "CodeReviewComment",
                    "phaseType": "SimplePhase",
                    "max_turn_step": 1,
                    "need_reflect": "False"
                },
                {
                    "phase": "CodeReviewModification",
                    "phaseType": "SimplePhase",
                    "max_turn_step": 1,
                    "need_reflect": "False"
                }
            ],
        phase_classes={"CodeReviewComment": CodeReviewCommentPhase, "CodeReviewModification": CodeReviewModificationPhase},
        phase_configs={"CodeReviewComment": environments["config_phase"]['CodeReviewComment'], "CodeReviewModification": environments["config_phase"]['CodeReviewModification']},
        model=model,
        memory=VectorMemory(embedding_function=embedding_function, context_label="CODE_REVIEW_COMPOSED_MEMORY"),
    )

chatdev.create_edge(
    sender=code_complete_all_composed_phase,
    receiver=code_review_composed_phase,
    keys={}
)

test_composed_phase : TestComposedPhase = chatdev.create_node(
        TestComposedPhase,
        name="test_composed_phase",
        cycle_num=3,
        composition=[{
                    "phase": "TestErrorSummary",
                    "phaseType": "SimplePhase",
                    "max_turn_step": 1,
                    "need_reflect": "False"
                },
                {
                    "phase": "TestModification",
                    "phaseType": "SimplePhase",
                    "max_turn_step": 1,
                    "need_reflect": "False"
                }
            ],
        phase_classes={"TestErrorSummary": TestErrorSummaryPhase, "TestModification": TestModificationPhase},
        phase_configs={"TestErrorSummary": environments["config_phase"]['TestErrorSummary'], "TestModification": environments["config_phase"]['TestModification']},
        model=model,
        memory=VectorMemory(embedding_function=embedding_function, context_label="TEST_COMPOSED_MEMORY"),
    )

chatdev.create_edge(
    sender=code_review_composed_phase,
    receiver=test_composed_phase,
    keys={}
)

environment_doc_phase : EnvironmentDocPhase = chatdev.create_node(
    EnvironmentDocPhase,
    name="environment_doc_phase",
    assistant_role_name="Programmer",
    instructor_role_name="Chief Technology Officer",
    assistant_instructions=environments["config_role"]["Programmer"],
    instructor_instructions=environments["config_role"]["Chief Technology Officer"],
    phase_instructions=environments["config_phase"]['EnvironmentDoc']['phase_prompt'],
    model=model,
    memory=VectorMemory(embedding_function=embedding_function, context_label="ENVIRONMENT_DOC_MEMORY"),
    max_turns=1,
    reflect_roles = {"ceo": "", "counselor": ""}
)

chatdev.create_edge(
    sender=test_composed_phase,
    receiver=environment_doc_phase,
    keys={}
)

manual_phase : ManualPhase = chatdev.create_node(
    ManualPhase,
    name="manual_phase",
    assistant_role_name="Chief Product Officer",
    instructor_role_name="Chief Executive Officer",
    assistant_instructions=environments["config_role"]["Chief Product Officer"],
    instructor_instructions=environments["config_role"]["Chief Executive Officer"],
    phase_instructions=environments["config_phase"]['Manual']['phase_prompt'],
    model=model,
    memory=VectorMemory(embedding_function=embedding_function, context_label="MANUAL_MEMORY"),
    max_turns=1,
)

chatdev.create_edge(
    sender=environment_doc_phase,
    receiver=manual_phase,
    keys={}
)

post_processing_phase: CustomNode = chatdev.create_node(
        CustomNode,
        "post_processing_phase",
    )

chatdev.create_edge(
    sender=manual_phase,
    receiver=post_processing_phase,
    keys={}
)
# Set forward callback
post_processing_phase.set_forward(post_processing)

# Exit information
chatdev.edge_to_exit(
    post_processing_phase,
    keys={}
)

chatdev.build()
chatdev.invoke(input={}, attributes=environments)