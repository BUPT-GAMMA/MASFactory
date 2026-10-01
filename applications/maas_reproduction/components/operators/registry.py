"""Declarative registry of native operator graph classes."""
from .native_agent_operator_graph import GenerateGraph, GenerateCoTGraph, SelfRefineGraph
from .multi_generate_cot_graph import MultiGenerateCoTGraph
from .sc_ensemble_graph import ScEnsembleGraph
from .programmer_graph import ProgrammerGraph
from .humaneval_test_graph import HumanEvalTestGraph

OPERATOR_REGISTRY = {
    "Generate": {"node_class": GenerateGraph},
    "GenerateCoT": {"node_class": GenerateCoTGraph},
    "SelfRefine": {"node_class": SelfRefineGraph},
    "MultiGenerateCoT": {"node_class": MultiGenerateCoTGraph},
    "ScEnsemble": {"node_class": ScEnsembleGraph},
    "Test": {"node_class": HumanEvalTestGraph},
    "Programmer": {"node_class": ProgrammerGraph},
}

__all__ = ["OPERATOR_REGISTRY"]
