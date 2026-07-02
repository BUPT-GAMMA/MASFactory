from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from masfactory import Graph, Model, Node, NodeTemplate, RootGraph, template_defaults
from masfactory.adapters.tool_adapter import ToolAdapter
from masfactory.utils.hook import masf_hook

import os
from .compiler import compile_aml
from .vibe_workflow import VibeWorkflow


def _is_aml_cache_path(path: str | Path | None) -> bool:
    return path is not None and Path(path).suffix.lower() == ".aml"


def _resolve_build_cache_path(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    cache_path = Path(path)
    if not _is_aml_cache_path(cache_path):
        raise ValueError(
            "VibeGraph cache must be an .aml file; use LegacyVibeGraph for graph_design cache."
        )
    return cache_path


def _aml_from_workflow_output(
    output: dict[str, Any],
    *,
    document_id: str,
    root_graph_id: str,
) -> str:
    raw_aml = output.get("aml")
    if isinstance(raw_aml, str) and raw_aml.strip():
        return raw_aml

    if "graph_design" in output:
        raise ValueError(
            "VibeGraph requires AML output; use LegacyVibeGraph for graph_design workflows."
        )
    raise ValueError(
        "VibeGraph build workflow must return a non-empty 'aml' field."
    )


class VibeGraph(Graph):
    """
    VibeGraphing:
    - Accept a reusable build workflow template (no registry).
    - The workflow is materialized inside a temporary RootGraph wrapper using MASFactory's native graph reuse path.
    - The workflow is responsible for producing AML.
    - VibeGraph is responsible for caching and compiling into runnable nodes/edges.
    """

    def __init__(
        self,
        name: str,
        invoke_model: Model,
        *,
        build_instructions: str,
        build_model: Model,
        build_workflow: NodeTemplate[Graph] = VibeWorkflow,
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
            build_instructions: Instructions used by the build workflow to produce AML.
            build_model: Model used by the build workflow.
            build_workflow: NodeTemplate for a reusable Graph build workflow.
            build_cache_path: Optional `.aml` cache file path.
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

    def _materialize_build_workflow(self) -> RootGraph:
        workflow = self._build_workflow
        if isinstance(workflow, Graph):
            raise TypeError(
                "build_workflow must be a NodeTemplate for a Graph, not a shared Graph instance."
            )
        if not isinstance(workflow, NodeTemplate):
            raise TypeError(
                f"build_workflow must be a NodeTemplate[Graph], got {type(workflow).__name__}"
            )

        wrapper = RootGraph(
            name=f"{self.name}_vibe_build",
            nodes=[("workflow", workflow)],
            edges=[
                (
                    "ENTRY",
                    "workflow",
                    {
                        "build_instructions": "",
                        "user_demand": "",
                        "user_advice": "",
                        "system_advice": "",
                    },
                ),
                ("workflow", "EXIT", {"aml": ""}),
            ],
        )
        return wrapper

    def _resolve_cache_path(self) -> Path | None:
        return _resolve_build_cache_path(self._build_cache_path)

    def _coerce_workflow_output(self, output: dict[str, Any]) -> str:
        return _aml_from_workflow_output(
            output,
            document_id=f"{self.name}.vibe_cache",
            root_graph_id=self.name,
        )

    def _load_cached_design(self, cache_path: Path) -> str | Path:
        return cache_path

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        """Build the graph by producing (or loading) AML and compiling it.

        - If `build_cache_path` is missing, it runs the build workflow to generate AML and caches it.
        - Otherwise, it loads the cached AML.
        - It then compiles the design into runnable nodes/edges on this graph.
        """
        tools = list(self._invoke_tools or [])
        raw_aml: str | Path | None = None
        cache_path = self._resolve_cache_path()
        cache_exists = cache_path is not None and os.path.exists(cache_path)
        # build AML design
        if cache_path is None or not cache_exists:
            build_workflow = self._materialize_build_workflow()
            file_fields = None
            if cache_path is not None:
                file_fields = {"aml": str(cache_path)}
            with template_defaults(
                model=self._build_model,
                file_fields=file_fields
            ):
                build_workflow.build()
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
                output, _attributes = build_workflow.invoke(
                    {
                        "build_instructions": build_instructions,
                        "user_demand": build_instructions,
                        "user_advice": "",
                        "system_advice": "",
                    }
                )
                if not isinstance(output, dict):
                    raise TypeError(
                        f"Vibe build workflow must return dict output, got {type(output).__name__}"
                    )
                raw_aml = self._coerce_workflow_output(output)
                if cache_path is not None:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(raw_aml, encoding="utf-8")
        else:
            raw_aml = self._load_cached_design(cache_path)

        compile_aml(
            target_graph=self,
            aml=raw_aml,
            model=self._invoke_model,
            tools=tools,
        )
        super().build()


__all__ = ["VibeGraph"]
