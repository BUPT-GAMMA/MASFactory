from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from masfactory import Graph, Model, Node, RootGraph, template_defaults
from masfactory.adapters.tool_adapter import ToolAdapter
from masfactory.utils.hook import masf_hook

import os
from .compiler import compile_graph_design, load_cached_graph_design, normalize_graph_design
from .vibe_workflow import VibeWorkflow

class VibeGraph(Graph):
    """
    VibeGraphing:
    - Accept a workflow object (no registry).
    - Workflow is responsible for parsing its own raw output into canonical graph_design.
    - VibeGraph is responsible for caching and compiling into runnable nodes/edges.
    """

    def __init__(
        self,
        name: str,
        invoke_model: Model,
        *,
        build_instructions: str,
        build_model: Model,
        build_workflow: RootGraph = VibeWorkflow,
        build_cache_path: str | Path | None = None,
        invoke_tools: list[Callable] | None = None,
        pull_keys: dict[str, dict|str] | None = None,
        push_keys: dict[str, dict|str] | None = None,
        attributes: dict[str, object] | None = None,
    ):
        """Create a VibeGraph.

        Args:
            name: Graph name.
            invoke_model: Model used by compiled agents for step execution.
            build_instructions: Instructions used by the build workflow to produce graph_design.
            build_model: Model used by the build workflow.
            build_workflow: RootGraph workflow that produces a graph_design artifact.
            build_cache_path: Optional cache file path for graph_design.
            invoke_tools: Optional list of tool callables available to compiled agents.
            pull_keys: Attribute pull rule for this graph.
            push_keys: Attribute push rule for this graph.
            attributes: Default attributes for this graph.
        """
        super().__init__(name=name, pull_keys=pull_keys, push_keys=push_keys, attributes=attributes)
        self._invoke_model = invoke_model
        self._build_workflow = build_workflow
        self._build_instructions = build_instructions
        self._build_model = build_model
        self._build_cache_path = build_cache_path
        self._invoke_tools = invoke_tools

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        """Build the graph by producing (or loading) a graph_design and compiling it.

        - If `build_cache_path` is missing, it runs `build_workflow` to generate graph_design and caches it.
        - Otherwise, it loads the cached graph_design.
        - It then compiles the design into runnable nodes/edges on this graph.
        """
        tools = list(self._invoke_tools or [])
        graph_design: dict[str, Any] = {}
        # build graph design
        if self._build_cache_path is None or not os.path.exists(self._build_cache_path):
            with template_defaults(
                model=self._build_model,
                file_fields={"graph_design": self._build_cache_path}
            ):
                self._build_workflow.build()
                tool_lines: list[str] = []
                if tools:
                    try:
                        tool_details = ToolAdapter(tools).details
                    except Exception:
                        tool_details = []
                        for tool in tools:
                            tool_details.append(
                                {
                                    "name": getattr(tool, "__name__", None) or type(tool).__name__,
                                    "description": getattr(tool, "__doc__", ""),
                                }
                            )

                    for tool_detail in tool_details:
                        tool_name = str(tool_detail.get("name") or "").strip() or "unknown_tool"
                        tool_doc = str(tool_detail.get("description") or "").strip()
                        tool_doc = " ".join(line.strip() for line in tool_doc.splitlines() if line.strip())
                        if not tool_doc:
                            tool_doc = "No docstring provided."
                        tool_lines.append(f"- {tool_name}: {tool_doc}")

                build_instructions = self._build_instructions + "\nAvailable tools (name: docstring):"
                if tool_lines:
                    build_instructions += "\n" + "\n".join(tool_lines)
                else:
                    build_instructions += "\n- None"
                output, _attributes = self._build_workflow.invoke(
                    {
                        "build_instructions": build_instructions,
                        "user_demand": build_instructions,
                        "user_advice": "",
                        "system_advice": "",
                    }
                )
                raw_graph_design = output.get("graph_design", {})
                graph_design = normalize_graph_design(raw_graph_design)
        else:
            graph_design = load_cached_graph_design(self._build_cache_path)

        # compile graph design
        compile_graph_design(
            target_graph=self,
            graph_design=graph_design,
            model=self._invoke_model,
            tools=tools,
        )
        super().build()


__all__ = ["VibeGraph"]
