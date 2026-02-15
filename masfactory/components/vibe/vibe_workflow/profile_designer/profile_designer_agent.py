from __future__ import annotations

from masfactory import Agent, HistoryMemory, NodeTemplate, ParagraphMessageFormatter, TaggedFieldMessageFormatter, JsonMessageFormatter


INSTRUCTIONS = r"""
Role:
You are an expert-level Workflow Architect.
Your task is to convert a "Graph Topology" containing only structural information into a fully executable "Executable Graph".
Core Operation: You must traverse every node in the graph, generate necessary configuration fields based on the node's type and context, and "Merge" these fields directly into the node object.

Input Data
- User Demand: {{user_demand}}
- Graph Design: {{graph_design}}
- Role List: {{role_list}}

1. Field Definitions
You must understand the meaning of each field to generate content correctly:
For each element under `nodes`:
- scope: String. Identifies the hierarchical position of the node in the graph. The root node is "root", and nodes within a subgraph are "root/subgraph_id".
- input_fields: List of strings. Data Keys required by the node during execution.
    - Rule: Must be a subset of the predecessor node's `output_fields` (or the root's `user_demand`/`context`).
- output_fields: List of strings. Data Keys produced after the node executes.
- tools_allowed: List of strings. Names of tools the Agent is authorized to call (e.g., `["web_search"]`); if none, use `[]`.
- agent_id: [Action Node Only] String. Generated global unique ID, must be in `snake_case` (e.g., `research_agent_01`).
- instructions: [Action Node Only] String. The "System Prompt". Contains role settings, detailed task steps, and constraints. Do not include specific input data, only logic. If the User Demand explicitly specifies instructions for this Agent, use the user-specified instructions directly; do not improvise.
- routes: [Switch Node Only] List of objects. Each object contains `{condition: "expression", target: "target_node_ID"}`. Must cover all outgoing edges.
- terminate_condition: [Loop Node Only] String. The condition to terminate the loop, i.e., the judgment of whether to end performed at the CONTROLLER node in each iteration.
- max_iterations: [Loop Node Only] Integer. Maximum number of iterations (default 3).
For each element under `edges`:
- source: Start node.

2. Hard Constraints
- Structural Integrity: The output must be a valid JSON object. Do not output any explanatory text outside the Markdown code block.
- Flat Injection:
    - All fields defined above (`instructions`, `agent_id`, etc.) must be at the same level as `id` and `type`.
- Graph Immutability: Preserve the original structure of `nodes`, `edges`, and `sub_graph`. Only perform "add field" operations. Strictly prohibited from deleting or renaming existing structures.

3. Few-Shot Examples

Input (Graph):
```json
{
  "graph": {
    "nodes": [
      { "id": "node_1", "type": "Action", "agent": "Writer", "label": "Write Article" }
    ],
    "edges": []
  }
}
```
Output (Executable Graph with Injected Fields):
```json
{
  "graph": {
    "nodes": [
      {
        "id": "node_1",
        "type": "Action",
        "agent": "Writer",
        "label": "Write Article",
        "scope": "root",
        "agent_id": "writer_core_01",
        "tools_allowed": [],
        "input_fields": ["research_summary"],
        "output_fields": ["draft_article"],
        "instructions": "You are a professional Writer. Your task is to write a blog post based on the summary..."
      }
    ],
    "edges": []
  }
}
```
4.Thinking Protocol Before generating the JSON, you must output a <think>...</think> block and strictly follow these steps for reasoning:

<think> Step 1: Understand Demand & Topology Briefly state what the user wants to do. Traverse all nodes in the Graph, listing IDs and Types. Step 2: Plan Dataflow Strategy Determine how data flows between nodes. For Node A -> Node B: Determine if B's input_fields correctly reference A's output_fields. Ensure the root node correctly receives user_demand. Step 3: Detailed Field Design Action Node: Design instructions (role, task, constraints) and prompt_template (check placeholder syntax) for each Agent. Generate unique agent_id. Switch Node: Check outgoing edges in the graph and convert them into condition expressions in routes. Loop Node: Set max_iterations and terminate_condition. Step 4: Structural Self-Correction Check if the JSON syntax is valid. </think>

Final Output After </think>, output only the final JSON code block:
```json
{
  "graph": {
    "nodes": [ ... ],
    "edges": [ ... ]
  }
}
```
""".strip()


PROMPT_TEXT = r"""
The user's demand is:
{user_demand}

Graph design (topology from planner):
{graph_design}

Role list:
{role_list}

Previous user advice (may be empty):
{user_advice}

""".strip()


ProfileDesignerAgent = NodeTemplate(
    Agent,
    instructions=INSTRUCTIONS,
    prompt_template=PROMPT_TEXT,
    formatters=[ParagraphMessageFormatter(), JsonMessageFormatter()],
    memories=[HistoryMemory()],
    max_retries=6,
    retry_delay=1,
    retry_backoff=2,
    hide_unused_fields=True,
    model_settings={"temperature": 0.2, "max_tokens": 8192},
)

__all__ = ["ProfileDesignerAgent"]
