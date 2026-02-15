"""GAIA planner/executor workflow graph.

Runs a 2-agent loop (Planner -> Executor) until the Planner emits `FINAL ANSWER: ...`.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict

from masfactory import Agent, CustomNode, HistoryMemory, Loop, OpenAIModel, RootGraph
from masfactory.core.message import ParagraphMessageFormatter, TwinsFieldTextFormatter

from .tools import gaia_tool_functions


_FINAL_RE = re.compile(r"(?im)^\s*FINAL\s+ANSWER\s*:\s*(.+?)\s*$")
_INSTRUCTION_RE = re.compile(r"(?im)^\s*INSTRUCTION\s*:\s*(.+?)\s*$")


PLANNER_SYSTEM_PROMPT = """You are Planner, the brain of a 2-agent Planner-Executor system for solving GAIA tasks.

Your responsibilities:
- Read the question and any referenced file paths.
- Decide what to do next and instruct the Executor in natural language.
- You MUST NOT call tools, run code, browse the web, or access files directly.
- You MUST NOT write code. If code is needed, instruct the Executor to write and run it.

Strategy:
- If the question can be answered directly from the prompt (no web/files), output FINAL ANSWER immediately.
- Otherwise, ask the Executor to solve the task end-to-end using the available tools and return the final answer candidate.

Protocol:
- If you need the Executor to do something, output exactly:
INSTRUCTION: <clear instruction to Executor>

- If you have enough information to answer, output exactly:
FINAL ANSWER: <answer>

- If you are stuck or further actions are unlikely to help, output FINAL ANSWER with your best guess (do not keep issuing INSTRUCTION forever).

GAIA final answer rules:
- Return only your answer (number / short phrase / comma-separated list).
- If the answer is a number, return only the number (no units unless specified).
- If the answer is a string, don't include articles, and don't use abbreviations.
- Do not output any text after the FINAL ANSWER line.
"""


EXECUTOR_SYSTEM_PROMPT = """You are Executor, the hands of a 2-agent Planner-Executor system for solving GAIA tasks.

Your responsibilities:
- Follow the Planner's instruction.
- Use tools to perform actions and return observations back to Planner.

Available tools:
- python_interpreter(code, timeout_s): run python (can use pandas/openpyxl/scipy when installed)
- read_file(path, max_bytes): read a local file from the repo
- ocr_image(path, lang, psm, max_chars, timeout_s): OCR a local image file to text
- web_search(query, max_results): search the web
- web_fetch(url, max_chars): fetch a URL and return extracted text

Best practices:
- For local attachments, start with read_file(path) to extract contents (it can parse .xlsx/.pdf/.docx/.pptx), then use python_interpreter only if needed.
- For image attachments, use read_file(path) (it runs OCR), or call ocr_image(path) for more control (language/psm).
- Prefer python_interpreter for calculations and for parsing/processing when you need computation beyond simple reading.
- Use web_search to find authoritative URLs, then web_fetch to extract only what you need.
- If tool output is long/noisy, summarize only the key facts needed for the final answer.

Protocol:
- When you reply to Planner, output exactly one line starting with:
OBSERVATION: <your concise result>

- If you have a strong final answer candidate, include it as:
FINAL_ANSWER_CANDIDATE=<answer>
(Still keep the message on a single OBSERVATION line.)

Rules:
- Do not provide a final answer to the user unless explicitly instructed by Planner.
- If you encounter an error, report it in OBSERVATION with enough detail for Planner to adjust.
"""


def _env(key: str) -> str | None:
    v = os.environ.get(key)
    return v.strip() if isinstance(v, str) and v.strip() else None


def _build_models(config: dict[str, Any]) -> tuple[OpenAIModel, OpenAIModel]:
    model_cfg = config.get("model") or {}
    tool_model_cfg = config.get("tool_model") or model_cfg

    default_api_key = _env("OPENAI_API_KEY")
    default_base_url = _env("OPENAI_BASE_URL") or _env("BASE_URL")

    tool_api_key = _env("TOOL_OPENAI_API_KEY") or default_api_key
    tool_base_url = _env("TOOL_OPENAI_BASE_URL") or _env("TOOL_BASE_URL") or default_base_url

    if not default_api_key or not default_base_url:
        raise RuntimeError("OPENAI_API_KEY and OPENAI_BASE_URL (or BASE_URL) must be set.")

    planner_model = OpenAIModel(
        model_name=model_cfg.get("model_name", "gpt-4o-mini"),
        api_key=default_api_key,
        base_url=default_base_url,
        invoke_settings={
            "temperature": model_cfg.get("temperature", 0.0),
            "max_tokens": model_cfg.get("max_tokens", 512),
        },
    )
    executor_model = OpenAIModel(
        model_name=tool_model_cfg.get("model_name", "gpt-4o-mini"),
        api_key=tool_api_key,
        base_url=tool_base_url,
        invoke_settings={
            "temperature": tool_model_cfg.get("temperature", 0.0),
            "max_tokens": tool_model_cfg.get("max_tokens", 1024),
        },
    )
    return planner_model, executor_model


def build_gaia_graph(config: Dict[str, Any]) -> RootGraph:
    root = RootGraph(name="gaia_solve_task")

    planner_model, executor_model = _build_models(config)

    max_turn = int(config.get("max_turn", 12) or 12)
    initial_previous_plan = str(config.get("initial_previous_plan") or "No solution yet.")
    initial_advice = str(config.get("initial_advice") or "No advice yet.")

    loop = root.create_node(
        Loop,
        name="gaia_loop",
        max_iterations=max_turn,
        attributes={
            "task_description": "",
            "previous_plan": initial_previous_plan,
            "advice": initial_advice,
            "done": False,
            "final_answer": "",
            "instruction": "",
            "observation": "",
        },
        initial_messages={
            "task_description": "",
            "previous_plan": initial_previous_plan,
            "advice": initial_advice,
            "done": False,
            "instruction": "",
            "observation": "",
            "final_answer": "",
        },
        terminate_condition_function=lambda _messages, attributes: bool(attributes.get("done")),
    )

    planner = loop.create_node(
        Agent,
        name="Planner",
        role_name="Planner",
        instructions=PLANNER_SYSTEM_PROMPT,
        formatters=[ParagraphMessageFormatter(), TwinsFieldTextFormatter()],
        prompt_template=(
            "TASK:\n{task_description}\n\n"
            "PREVIOUS PLANNER OUTPUT:\n{previous_plan}\n\n"
            "EXECUTOR OBSERVATION:\n{advice}\n\n"
            "Output either an INSTRUCTION or a FINAL ANSWER."
        ),
        model=planner_model,
        model_settings={"temperature": 0.0, "max_tokens": int(config.get("planner_max_tokens", 512) or 512)},
        memories=[HistoryMemory(top_k=30, memory_size=2000)],
        hide_unused_fields=True,
    )

    parse_planner = loop.create_node(
        CustomNode,
        name="parse_planner",
        pull_keys=None,
        push_keys=None,
    )

    def _parse_planner_forward(messages: dict, attributes: dict) -> dict:
        text = str(messages.get("message", "") or "")
        task_desc = str(attributes.get("task_description", "") or "")
        attributes["previous_plan"] = text
        m_final = _FINAL_RE.search(text)
        if m_final:
            attributes["done"] = True
            attributes["final_answer"] = m_final.group(1).strip()
            attributes["instruction"] = ""
            return {
                "done": True,
                "final_answer": attributes["final_answer"],
                "instruction": "",
                "previous_plan": text,
                "task_description": task_desc,
            }

        m_inst = _INSTRUCTION_RE.search(text)
        inst = m_inst.group(1).strip() if m_inst else text.strip()
        attributes["done"] = False
        attributes["final_answer"] = ""
        attributes["instruction"] = inst
        return {
            "done": False,
            "final_answer": "",
            "instruction": inst,
            "previous_plan": text,
            "task_description": task_desc,
        }

    parse_planner.set_forward(_parse_planner_forward)

    executor_tools = gaia_tool_functions()
    executor_max_tokens = int(config.get("executor_max_tokens", 1024) or 1024)

    # Tool-enabled executor agent (kept outside the graph to avoid being scheduled as an always-ready node).
    # MASFactory Agent handles the tool-call loop internally.
    executor_agent = Agent(
        name="ExecutorAgent",
        role_name="Executor",
        instructions=EXECUTOR_SYSTEM_PROMPT,
        formatters=[ParagraphMessageFormatter(), TwinsFieldTextFormatter()],
        prompt_template=(
            "TASK (for context):\n{task_description}\n\n"
            "PLANNER INSTRUCTION:\n{instruction}\n\n"
            "Return exactly ONE line:\n"
            "OBSERVATION: <your concise result>\n"
            "Optionally append: FINAL_ANSWER_CANDIDATE=<answer> (still on the same line)."
        ),
        tools=executor_tools,
        model=executor_model,
        model_settings={"temperature": 0.0, "max_tokens": executor_max_tokens},
        memories=[HistoryMemory(top_k=40, memory_size=4000)],
        push_keys={"advice": "Executor observation (single-line)"},
        hide_unused_fields=True,
    )

    executor = loop.create_node(
        CustomNode,
        name="Executor",
        pull_keys=None,
        push_keys=None,
    )

    def _executor_forward(messages: dict, attributes: dict) -> dict:
        done = bool(messages.get("done"))
        final_answer = str(messages.get("final_answer", "") or "").strip()
        previous_plan = str(messages.get("previous_plan", "") or "").strip()
        instruction = str(messages.get("instruction", "") or "").strip()
        task_desc = str(messages.get("task_description", "") or "").strip()

        # If planner is done, skip tool use and just forward state to the controller.
        if done:
            return {
                "advice": "",
                "done": True,
                "final_answer": final_answer,
                "previous_plan": previous_plan,
                "task_description": task_desc,
            }

        if not instruction:
            obs = "OBSERVATION: (no instruction)"
            return {
                "advice": obs,
                "done": False,
                "final_answer": "",
                "previous_plan": previous_plan,
                "task_description": task_desc,
            }

        out = executor_agent.step({"task_description": task_desc, "instruction": instruction})
        obs = str(out.get("advice") or "").strip()
        if not obs.lower().startswith("observation:"):
            obs = f"OBSERVATION: {obs}".strip()

        return {
            "advice": obs,
            "done": False,
            "final_answer": "",
            "previous_plan": previous_plan,
            "task_description": task_desc,
        }

    executor.set_forward(_executor_forward)

    # Wiring inside the loop:
    loop.edge_from_controller(
        receiver=planner,
        keys={
            "task_description": "GAIA task prompt",
            "previous_plan": "Previous planner output",
            "advice": "Executor observation",
        },
    )
    loop.create_edge(planner, parse_planner, keys={"message": "Planner output"})

    loop.create_edge(
        parse_planner,
        executor,
        keys={
            "done": "Planner done flag",
            "final_answer": "Planner final answer",
            "previous_plan": "Planner raw output",
            "instruction": "Planner instruction",
            "task_description": "GAIA task prompt",
        },
    )

    # Single feedback edge to controller to avoid multi-in-edge deadlocks.
    loop.edge_to_controller(
        sender=executor,
        keys={
            "task_description": "GAIA task prompt",
            "previous_plan": "Planner output snapshot",
            "advice": "Executor observation",
            "done": "Done flag",
            "final_answer": "Final answer",
        },
    )

    # Entry/exit wiring.
    root.edge_from_entry(loop, keys={"task_description": "GAIA task prompt"})
    root.edge_to_exit(loop, keys={"final_answer": "Final answer", "done": "Done flag"})

    root.build()
    return root
