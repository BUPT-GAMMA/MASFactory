from model import model
from masfactory import RootGraph, Loop, Agent, CustomNode, NodeTemplate
from masfactory.core.multimodal import ImageAsset
from prompts import (IO_INSTRUCTIONS, CCOT_STEP1_INSTRUCTIONS, CCOT_STEP2_INSTRUCTIONS,
                     DDCOT_STEP1_INSTRUCTIONS, DDCOT_STEP2_INSTRUCTIONS,
                     IO_INSTRUCTIONS_MMVET, CCOT_STEP2_INSTRUCTIONS_MMVET, DDCOT_STEP2_INSTRUCTIONS_MMVET,
                     OTHER_ANSWERS_PREFIX, OTHER_ANSWERS_SUFFIX)
from Dataset import create_prompt

# ---- ScienceQA agents ----
IO_Agent = NodeTemplate(
    Agent, model=model,
    instructions=IO_INSTRUCTIONS,
    prompt_template="{io_prompt}\n{question_image}",
)

CCoT_Agent_step1 = NodeTemplate(
    Agent, model=model,
    instructions=CCOT_STEP1_INSTRUCTIONS,
    prompt_template="{ccot_step1_prompt}\n{question_image}",
)

CCoT_Agent_step2 = NodeTemplate(
    Agent, model=model,
    instructions=CCOT_STEP2_INSTRUCTIONS,
    prompt_template="{ccot_step2_prompt}\n{question_image}",
)

DDCoT_Agent_step1 = NodeTemplate(
    Agent, model=model,
    instructions=DDCOT_STEP1_INSTRUCTIONS,
    prompt_template="{ddcot_step1_prompt}\n{question_image}",
)

DDCoT_Agent_step2 = NodeTemplate(
    Agent, model=model,
    instructions=DDCOT_STEP2_INSTRUCTIONS,
    prompt_template="{ddcot_step2_prompt}\n{question_image}",
)

# ---- mm-vet agents (no "The answer is X" format) ----
IO_Agent_MMVET = NodeTemplate(
    Agent, model=model,
    instructions=IO_INSTRUCTIONS_MMVET,
    prompt_template="{io_prompt}\n{question_image}",
)

CCoT_Agent_step1_MMVET = CCoT_Agent_step1

CCoT_Agent_step2_MMVET = NodeTemplate(
    Agent, model=model,
    instructions=CCOT_STEP2_INSTRUCTIONS_MMVET,
    prompt_template="{ccot_step2_prompt}\n{question_image}",
)

DDCoT_Agent_step1_MMVET = DDCoT_Agent_step1

DDCoT_Agent_step2_MMVET = NodeTemplate(
    Agent, model=model,
    instructions=DDCOT_STEP2_INSTRUCTIONS_MMVET,
    prompt_template="{ddcot_step2_prompt}\n{question_image}",
)


STRATEGY_INDICES = {"io": 0, "ccot": 1, "ddcot": 2}
_EMPTY_ANSWERS = [["", "", ""], ["", "", ""], ["", "", ""]]


def _get_round_index(all_answers):
    """Return the current round index (first empty row in all_answers).

    all_answers: 3x3 list, each row = [io, ccot, ddcot].
    """
    if not isinstance(all_answers, list) or len(all_answers) == 0:
        return 0
    for i, row in enumerate(all_answers):
        if not any(row):
            return i
    return len(all_answers)


def _build_other_answers(all_answers, strategy, round_index):
    """Build the other-answers context string for one strategy's stage 1."""
    if round_index == 0:
        return ""

    prev_round = all_answers[round_index - 1]
    if not any(prev_round):
        return ""

    current_idx = STRATEGY_INDICES[strategy]
    other_indices = [i for i in range(3) if i != current_idx]

    answers = []
    for idx in other_indices:
        answer_text = prev_round[idx] or "(no answer)"
        answers.append(f" One answer: ```{answer_text}```")

    return (
        OTHER_ANSWERS_PREFIX
        + "\n\n".join(answers)
        + "\n"
        + OTHER_ANSWERS_SUFFIX
    )


def build_debate_prompts(input, attributes):
    """Build user prompts for each agent (complement to Agent.instruction).

    Agent.instruction = system prompt (role, format, constraints).
    PromptBuilder output = user message (question, options, other_answers, image).
    """
    image_path = input.get("image_path", "")
    all_answers = attributes.get("all_answers", _EMPTY_ANSWERS)

    item = input.get("question", {})
    if isinstance(item, dict):
        question = item.get("question", "")
        options = item.get("choices", None)
    else:
        question = str(item) if item else ""
        options = None

    if not isinstance(all_answers, list):
        all_answers = _EMPTY_ANSWERS

    base_question = create_prompt(question, options)
    round_index = _get_round_index(all_answers)

    io_other = _build_other_answers(all_answers, "io", round_index)
    ccot_other = _build_other_answers(all_answers, "ccot", round_index)
    ddcot_other = _build_other_answers(all_answers, "ddcot", round_index)

    io_content = (io_other + "\n" + base_question) if io_other else base_question
    ccot_s1_content = (ccot_other + "\n" + base_question) if ccot_other else base_question
    ccot_s2_content = base_question
    ddcot_s1_content = (ddcot_other + "\n" + base_question) if ddcot_other else base_question
    ddcot_s2_content = base_question

    return {
        "io_prompt":           io_content,
        "ccot_step1_prompt":   ccot_s1_content,
        "ccot_step2_prompt":   ccot_s2_content,
        "ddcot_step1_prompt":  ddcot_s1_content,
        "ddcot_step2_prompt":  ddcot_s2_content,
        "question_image":      ImageAsset.from_path(image_path) if image_path else "",
    }


PromptBuilder = NodeTemplate(
    CustomNode,
    forward=build_debate_prompts,
    pull_keys={"all_answers": ""},
)


def collect_debate_answers(input, attributes):
    """Collect the current round's answers and merge two-stage outputs.

    - IO: single-stage
    - CCoT: scene_graph (step1) + ccot_answer (step2)
    - DDCOT: sub_questions (step1) + ddcot_answer (step2)

    All agent outputs arrive via edges; all_answers is read from loop attributes.
    """
    import json as _json

    all_answers = attributes.get("all_answers", _EMPTY_ANSWERS)
    if not isinstance(all_answers, list) or len(all_answers) == 0:
        all_answers = _EMPTY_ANSWERS

    round_index = _get_round_index(all_answers)
    if round_index >= len(all_answers):
        round_index = len(all_answers) - 1

    io_ans = input.get("io_answer", "")

    sg = input.get("scene_graph", "")
    if isinstance(sg, (dict, list)):
        sg = _json.dumps(sg, ensure_ascii=False)
    ccot_ans = input.get("ccot_answer", "")
    ccot_combined = f"Scene graph:\n{sg}\n\nAnswer:\n{ccot_ans}"

    sq = input.get("sub_questions", "")
    if isinstance(sq, (dict, list)):
        sq = _json.dumps(sq, ensure_ascii=False)
    ddcot_ans = input.get("ddcot_answer", "")
    ddcot_combined = f"Sub-questions:\n{sq}\n\nAnswer:\n{ddcot_ans}"

    all_answers[round_index][0] = io_ans
    all_answers[round_index][1] = ccot_combined
    all_answers[round_index][2] = ddcot_combined

    return {"all_answers": all_answers}


AnswerCollector = NodeTemplate(
    CustomNode,
    forward=collect_debate_answers,
    pull_keys={"all_answers": ""},
    push_keys={"all_answers": ""},
)

_LOOP_ATTRS = {
    "io_answer": "",
    "ccot_answer": "",
    "ddcot_answer": "",
    "all_answers": "",
}
_LOOP_COMMON_NODES = [
    ("PromptBuilder", PromptBuilder),
    ("AnswerCollector", AnswerCollector),
]
_LOOP_EDGES = [
    ("controller", "PromptBuilder", {"question": "", "image_path": ""}),
    ("PromptBuilder", "IO_Agent", {"io_prompt": "", "question_image": ""}),
    ("IO_Agent", "AnswerCollector", {"io_answer": ""}),
    ("PromptBuilder", "CCoT_Agent_1", {"ccot_step1_prompt": "", "question_image": ""}),
    ("PromptBuilder", "CCoT_Agent_2", {"ccot_step2_prompt": "", "question_image": ""}),
    ("CCoT_Agent_1", "CCoT_Agent_2", {"scene_graph": ""}),
    ("CCoT_Agent_1", "AnswerCollector", {"scene_graph": ""}),
    ("CCoT_Agent_2", "AnswerCollector", {"ccot_answer": ""}),
    ("PromptBuilder", "DDCoT_Agent_1", {"ddcot_step1_prompt": "", "question_image": ""}),
    ("PromptBuilder", "DDCoT_Agent_2", {"ddcot_step2_prompt": "", "question_image": ""}),
    ("DDCoT_Agent_1", "DDCoT_Agent_2", {"sub_questions": ""}),
    ("DDCoT_Agent_1", "AnswerCollector", {"sub_questions": ""}),
    ("DDCoT_Agent_2", "AnswerCollector", {"ddcot_answer": ""}),
    ("AnswerCollector", "controller", {"all_answers": ""}),
]
_ROOT_EDGES = [
    ("entry", "debate_round", {"question": "", "image_path": ""}),
    ("debate_round", "exit", {"all_answers": ""}),
]

LoopD = NodeTemplate(
    Loop, max_iterations=3, attributes=_LOOP_ATTRS,
    nodes=[
        ("IO_Agent", IO_Agent),
        ("CCoT_Agent_1", CCoT_Agent_step1),
        ("CCoT_Agent_2", CCoT_Agent_step2),
        ("DDCoT_Agent_1", DDCoT_Agent_step1),
        ("DDCoT_Agent_2", DDCoT_Agent_step2),
    ] + _LOOP_COMMON_NODES,
    edges=_LOOP_EDGES,
)

LoopD_MMVET = NodeTemplate(
    Loop, max_iterations=3, attributes=_LOOP_ATTRS,
    nodes=[
        ("IO_Agent", IO_Agent_MMVET),
        ("CCoT_Agent_1", CCoT_Agent_step1_MMVET),
        ("CCoT_Agent_2", CCoT_Agent_step2_MMVET),
        ("DDCoT_Agent_1", DDCoT_Agent_step1_MMVET),
        ("DDCoT_Agent_2", DDCoT_Agent_step2_MMVET),
    ] + _LOOP_COMMON_NODES,
    edges=_LOOP_EDGES,
)


def make_graph(dataset="ScienceQA"):
    """Create a RootGraph with the appropriate agent set for the dataset."""
    loop = LoopD_MMVET if dataset == "mm-vet" else LoopD
    return RootGraph(name="DMAD", nodes=[("debate_round", loop)], edges=_ROOT_EDGES)


DMAD_GRAPH = make_graph("ScienceQA")
