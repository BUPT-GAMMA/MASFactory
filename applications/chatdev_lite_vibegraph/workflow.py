from __future__ import annotations

from pathlib import Path

from masfactory import CustomNode, Loop, Model, RootGraph
from masfactory.components.vibe.vibe_graph import VibeGraph
from applications.chatdev_lite_vibegraph.tools import (
    generate_meta,
    _make_codes_check_and_processing_forward,
    init_workdir_forward,
    load_chatdev_prompt,
    load_build_instructions,
    run_tests_tool,
    test_terminate_condition,
)

def build_chatdev_lite_vibegraph(*, model: Model) -> RootGraph:
    """
    ChatDev Lite (VibeGraph) using `VibeGraph` for each phase.

    Each phase is a `VibeGraph` subgraph auto-generated from `build_instructions`.
    In each phase you only edit: `build_instructions`, `pull_keys`, `push_keys`.
    """

    graph = RootGraph(
        name="chatdev_lite_vibegraph",
        attributes={
            "task": "Write a Ping-Pong (Pong) game, use Python and ultimately provide an application that can be run directly.",
            "chatdev_prompt": load_chatdev_prompt(),
            "gui": "A graphical user interface is required.",
            "modality": None,
            "language": None,
            "codes": None,
            "directory": None,
            "work_dir": None,
            "log_filepath": None,
            "error_summary": "",
            "test_reports": "",
            "exist_bugs_flag": True,
            "saved_code_files": None,
            "coding_code_files": None,
        },
    )

    cache_dir = Path(__file__).resolve().parent / "assets" / "cache"  # ./assets/cache
    graph_design_cache_dir = cache_dir / "graph_design"
    graph_design_cache_dir.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------
    # 0) Workdir init (logs + code files)
    # ----------------------------------------
    init_workdir = graph.create_node(CustomNode, name="init_workdir", forward=init_workdir_forward)

    # ----------------------------------------
    # 1) Demand Analysis
    # ----------------------------------------
    demand_analysis = graph.create_node(
        VibeGraph,
        name="demand_analysis_phase",
        invoke_model=model,     
        build_instructions=load_build_instructions("demand_analysis_phase"),
        build_model=model,
        build_cache_path=str(graph_design_cache_dir / "demand_analysis.graph_design.json"),
        pull_keys={
            "task": "The task prompt for software development",
            "chatdev_prompt": "Background prompt (optional)",
        },
        # Pre-seed outputs so Loop can update common keys even if its push_keys is missing.
        attributes={"modality": None},
        # Keep description short; enforce 1-word output via prompt.
        push_keys={"modality": "ONE_WORD"},
    )
    graph.edge_from_entry(receiver=init_workdir, keys={})
    graph.create_edge(sender=init_workdir, receiver=demand_analysis, keys={})

    # ----------------------------------------
    # 2) Language Choose
    # ----------------------------------------
    language_choose = graph.create_node(
        VibeGraph,
        name="language_choose_phase",
        invoke_model=model,
        build_instructions=load_build_instructions("language_choose_phase"),
        build_model=model,
        build_cache_path=str(graph_design_cache_dir / "language_choose.graph_design.json"),
        pull_keys={
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "chatdev_prompt": "Background prompt (optional)",
        },
        attributes={"language": None},
        # Keep description short; enforce 1-word output via prompt.
        push_keys={"language": "ONE_WORD"},
    )
    graph.create_edge(sender=demand_analysis, receiver=language_choose, keys={})

    # ----------------------------------------
    # 3) Coding
    # ----------------------------------------
    coding = graph.create_node(
        VibeGraph,
        name="coding_phase",
        invoke_model=model,
        build_instructions=load_build_instructions("coding_phase"),
        build_model=model,
        build_cache_path=str(graph_design_cache_dir / "coding.graph_design.json"),
        pull_keys={
            "task": "The task prompt for software development",
            "modality": "The product modality",
            "language": "The programming language",
            "chatdev_prompt": "Background prompt (optional)",
            "gui": "GUI requirements (optional)",
        },
        attributes={"codes": None},
        push_keys={"codes": "Source code for the MVP (include filenames; runnable)"},
    )
    graph.create_edge(sender=language_choose, receiver=coding, keys={})

    save_codes_after_coding = graph.create_node(
        CustomNode,
        name="save_codes_after_coding",
        forward=_make_codes_check_and_processing_forward(phase_info="Coding"),
    )

    graph.create_edge(sender=coding, receiver=save_codes_after_coding, keys={})

    # ----------------------------------------
    # 4) Test Loop (ErrorSummary -> Modification)
    # ----------------------------------------
    test_loop = graph.create_node(
        Loop,
        name="test_loop",
        max_iterations=3,
        terminate_condition_function=test_terminate_condition,
    )
    graph.create_edge(sender=save_codes_after_coding, receiver=test_loop, keys={})

    run_tests = test_loop.create_node(
        CustomNode,
        name="run_tests",
        forward=run_tests_tool,
    )

    test_error_summary = test_loop.create_node(
        VibeGraph,
        name="test_error_summary_phase",
        invoke_model=model,
        build_instructions=load_build_instructions("test_error_summary_phase"),
        build_model=model,
        build_cache_path=str(graph_design_cache_dir / "test_error_summary.graph_design.json"),
        pull_keys={
            "task": "The task prompt for software development",
            "language": "The programming language / stack",
            "codes": "Current source code",
            "test_reports": "Existing test reports (if any)",
            "exist_bugs_flag": "Whether the software has bugs (from actual execution)",
            "chatdev_prompt": "Background prompt (optional)",
        },
        attributes={"error_summary": ""},
        push_keys={"error_summary": "Summary of errors found in test_reports"},
    )

    test_modification = test_loop.create_node(
        VibeGraph,
        name="test_modification_phase",
        invoke_model=model,
        build_instructions=load_build_instructions("test_modification_phase"),
        build_model=model,
        build_cache_path=str(graph_design_cache_dir / "test_modification.graph_design.json"),
        pull_keys={
            "task": "The task prompt for software development",
            "language": "The programming language / stack",
            "test_reports": "Test reports / errors",
            "error_summary": "Summary of errors to fix",
            "codes": "Current source code",
            "chatdev_prompt": "Background prompt (optional)",
        },
        attributes={"codes": None},
        push_keys={"codes": "Updated code after fixing issues"},
    )

    save_codes_after_test_modification = test_loop.create_node(
        CustomNode,
        name="save_codes_after_test_modification",
        forward=_make_codes_check_and_processing_forward(
            phase_info="TestModification",
            update_existing_only=True,
            skip_when_no_bugs=True,
        ),
    )

    test_loop.edge_from_controller(receiver=run_tests, keys={})
    test_loop.create_edge(sender=run_tests, receiver=test_error_summary, keys={})
    test_loop.create_edge(sender=test_error_summary, receiver=test_modification, keys={})
    test_loop.create_edge(sender=test_modification, receiver=save_codes_after_test_modification, keys={})
    test_loop.edge_to_controller(sender=save_codes_after_test_modification, keys={})

    # ----------------------------------------
    # Post Processing (lightweight)
    # ----------------------------------------
    post_processing = graph.create_node(
        CustomNode,
        name="post_processing",
        forward=generate_meta(
            keys=["task", "modality", "language", "codes"],
            meta_filename="meta.txt",
        ),
    )
    graph.create_edge(sender=test_loop, receiver=post_processing, keys={})
    graph.edge_to_exit(sender=post_processing, keys={})

    return graph
