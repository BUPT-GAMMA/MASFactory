"""Explicit runtime dependency assembly for MaAS."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
from typing import Any
from .settings import RuntimeSettings
from .seed import seed_everything
from ..models.model_factory import create_shared_model
from ..models.embeddings import EmbeddingProvider, FakeEmbeddingProvider
from ..adapters.dataset_loader import DatasetLoader
from ..benchmarks import GSM8KScorer, MATHScorer, HumanEvalScorer
from ..adapters.cost_tracker import CostTracker
from ..adapters.artifact_store import ArtifactStore
from ..adapters.code_executor import CodeExecutor
from ..source_compat import (
    HumanEvalPublicTestRepository,
    SourceHumanEvalExecutor,
    compile_sc_ensemble_xml_prompt,
    parse_solution_letter_xml,
    sanitize as source_sanitize,
)
from .checkpoint_manager import CheckpointManager
from ..training.batch_accumulator import BatchAccumulator
from .. import contracts
from applications.maas_reproduction.components.operators.registry import OPERATOR_REGISTRY
from applications.maas_reproduction.components.operators.programmer_graph.programmer_core import ProgrammerCore
from applications.maas_reproduction.components.operators.humaneval_test_graph import HumanEvalTestProtocol
from applications.maas_reproduction.workflow import build_train_root_graph, build_test_root_graph
from .dependencies import RuntimeDependencies
from .prompt_loader import PromptLoader
from .run_logger import RunLogger
from .source_controller_bundle import (
    load_source_controller_bundle,
    validate_controller_distribution_fixtures,
    validate_query_embedding_fixtures,
)

RuntimeContext = RuntimeDependencies

class _UsageManager:
    """Small injected cost counter used when no external manager is supplied."""
    def __init__(self, *, input_rate: float | None, output_rate: float | None) -> None:
        self.total_cost = 0.0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.cost_reliable = input_rate is not None and output_rate is not None
        self.cost_reliability_error = (
            None
            if self.cost_reliable
            else "model pricing is not configured; set input/output cost per 1k tokens"
        )
        self.input_rate = input_rate
        self.output_rate = output_rate

    def record_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        prompt_tokens = max(int(prompt_tokens), 0)
        completion_tokens = max(int(completion_tokens), 0)
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        if self.cost_reliable:
            self.total_cost += (
                prompt_tokens / 1000.0 * float(self.input_rate)
                + completion_tokens / 1000.0 * float(self.output_rate)
            )

def build_runtime(settings: RuntimeSettings, *, fake: bool = False, manager: Any = None,
                  output_root_override: Path | None = None,
                  subset: int | None = None,
                  source_bundle_path: Path | None = None) -> RuntimeContext:
    # Resolve and create the run directory before loading optional runtime
    # dependencies, so even bootstrap failures are persisted in error.log.
    output_root = output_root_override or settings.output_root
    if not output_root.is_absolute() and output_root.as_posix() == "assets/output":
        output_root = Path(__file__).parents[2] / "assets" / "output"
    if output_root_override is None:
        run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S_%f")
        output_root = output_root / run_id
    checkpoint = CheckpointManager(output_root / "checkpoints")
    artifact_store = ArtifactStore(output_root, results_root=output_root / "results")
    run_logger = RunLogger(output_root, output_root.name)
    try:
        import torch

        seed_everything(settings.seed)
        model = create_shared_model(settings.model, fake=fake)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        embedder = (
            FakeEmbeddingProvider()
            if fake
            else EmbeddingProvider(settings.embedding_model, device=str(device))
        )
        expected_catalog = contracts.operator_catalog_for(settings.dataset)
        from ..models.controller import MultiLayerController
        if source_bundle_path is not None:
            if settings.mode != "test":
                raise ValueError("source Controller bundles are valid only in test mode")
            source_bundle = load_source_controller_bundle(
                source_bundle_path,
                expected_dataset=settings.dataset,
                expected_catalog=expected_catalog,
                expected_embedding_model=settings.embedding_model,
            )
            validate_query_embedding_fixtures(source_bundle, embedder)
            catalog = source_bundle.operator_catalog
            embeddings = source_bundle.operator_embeddings.to(device)
            controller = MultiLayerController(
                input_dim=source_bundle.controller_spec["input_dim"],
                hidden_dim=source_bundle.controller_spec["hidden_dim"],
                num_layers=source_bundle.controller_spec["num_layers"],
                embedding_provider=embedder,
                device=device,
            ).to(device)
            controller.load_state_dict(source_bundle.controller_state_dict, strict=True)
            controller.requires_grad_(False)
            controller.eval()
            validate_controller_distribution_fixtures(source_bundle, controller)
        else:
            catalog = expected_catalog
            embeddings = embedder.encode_many(catalog).to(device)
            # Move the fully-created policy before the optimizer captures params.
            controller = MultiLayerController(embedding_provider=embedder, device=device).to(device)
    except Exception as exc:
        run_logger.error(stage="bootstrap_dependencies", error=exc)
        raise
    registry = {name: dict(spec) for name, spec in OPERATOR_REGISTRY.items() if name in catalog}
    usage_manager = manager if manager is not None else _UsageManager(
        input_rate=settings.model.input_cost_per_1k_tokens,
        output_rate=settings.model.output_cost_per_1k_tokens,
    )
    if not callable(getattr(usage_manager, "record_usage", None)):
        raise TypeError("usage manager must provide record_usage(prompt_tokens, completion_tokens)")
    prompt_loader = PromptLoader(Path(__file__).parents[2] / "assets" / "prompts")
    programmer_instruction = prompt_loader.load("Programmer", settings.dataset)

    def _problem_from_payload(payload: dict[str, Any]) -> str:
        problem = payload.get("problem")
        if problem:
            return str(problem)
        invocation = payload.get("operator_invocation")
        if isinstance(invocation, dict):
            return str(invocation.get("problem", ""))
        return str(getattr(invocation, "problem", ""))

    def _entrypoint_from_payload(payload: dict[str, Any]) -> str:
        entrypoint = payload.get("entry_point")
        if entrypoint:
            return str(entrypoint)
        invocation = payload.get("operator_invocation")
        if isinstance(invocation, dict):
            return str(invocation.get("entry_point", ""))
        return str(getattr(invocation, "entry_point", ""))

    def _invoke_model(payload: dict[str, Any], instruction: str, *, user_content: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        problem = _problem_from_payload(payload)
        feedback = payload.get("feedback", "")
        if user_content is None:
            user_content = problem if not feedback else f"Problem:\n{problem}\n\nFeedback:\n{feedback}"
        messages = []
        if instruction:
            messages.append({"role": "system", "content": instruction})
        messages.append({"role": "user", "content": user_content})
        tracker = getattr(model, "token_tracker", None)
        before_input = int(getattr(tracker, "total_input_usage", 0) or 0)
        before_output = int(getattr(tracker, "total_output_usage", 0) or 0)
        response = model.invoke(messages, tools=None)
        usage = response.get("usage", {}) if isinstance(response, dict) else {}
        # MASFactory OpenAIModel records usage on token_tracker and does not
        # put it in the returned response mapping.  Prefer explicit provider
        # usage when present, otherwise use the tracker delta.
        explicit_input = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        explicit_output = usage.get("completion_tokens") if isinstance(usage, dict) else None
        after_input = int(getattr(tracker, "total_input_usage", before_input) or 0)
        after_output = int(getattr(tracker, "total_output_usage", before_output) or 0)
        prompt_tokens = int(explicit_input) if explicit_input is not None else after_input - before_input
        completion_tokens = int(explicit_output) if explicit_output is not None else after_output - before_output
        usage = dict(usage) if isinstance(usage, dict) else {}
        usage.setdefault("prompt_tokens", prompt_tokens)
        usage.setdefault("completion_tokens", completion_tokens)
        usage.setdefault("total_tokens", prompt_tokens + completion_tokens)
        usage_manager.record_usage(prompt_tokens, completion_tokens)
        return response, usage

    def adapter(payload):
        response, usage = _invoke_model(payload, str(payload.get("instructions", "")))
        return {"solution": response.get("content", ""), "metadata": {"usage": usage}}

    def _humaneval_code_fill(payload: dict[str, Any], prompt: str, entrypoint: str | None) -> dict[str, Any]:
        response, usage = _invoke_model(payload, "", user_content=prompt)
        solution = source_sanitize(str(response.get("content", "")), entrypoint=entrypoint)
        return {"solution": solution, "metadata": {"usage": usage}}

    def humaneval_generate_adapter(payload):
        return _humaneval_code_fill(
            payload,
            _problem_from_payload(payload),
            _entrypoint_from_payload(payload),
        )

    def generate_cot_adapter(payload):
        response, usage = _invoke_model(payload, prompt_loader.load("GenerateCoT", settings.dataset))
        return {"solution": response.get("content", ""), "metadata": {"usage": usage}}

    def multi_generate_cot_adapter(payload):
        response, usage = _invoke_model(payload, prompt_loader.load("MultiGenerateCoT", settings.dataset))
        return {"solution": response.get("content", ""), "metadata": {"usage": usage}}

    def self_refine_adapter(payload):
        problem = _problem_from_payload(payload)
        solution = payload.get("current_solution", "")
        content = f"Problem:\n{problem}\n\nCurrent solution:\n{solution}"
        response, usage = _invoke_model(payload, prompt_loader.load("SelfRefine", settings.dataset), user_content=content)
        return {"solution": response.get("content", ""), "metadata": {"usage": usage}}

    def humaneval_self_refine_adapter(payload):
        problem = _problem_from_payload(payload)
        solution = payload.get("current_solution", "")
        template = prompt_loader.load("SelfRefine", "HumanEval")
        prompt = template.format(problem=problem, solution=solution)
        return _humaneval_code_fill(payload, prompt, None)

    def bootstrap_generate_adapter(payload):
        problem = _problem_from_payload(payload)
        code_output = payload.get("current_solution", "")
        content = f"Problem:\n{problem}\n\nCode output:\n{code_output}"
        instruction = prompt_loader.load("BootstrapGenerate", settings.dataset)
        response, usage = _invoke_model(payload, instruction, user_content=content)
        return {"solution": response.get("content", ""), "metadata": {"usage": usage}}

    def sc_ensemble_adapter(payload):
        problem = _problem_from_payload(payload)
        candidates = tuple(payload.get("candidates", ()))
        labeled = "\n\n".join(f"{chr(65 + i)}:\n{candidate}" for i, candidate in enumerate(candidates))
        content = f"Problem:\n{problem}\n\nCandidate solutions:\n{labeled}"
        response, usage = _invoke_model(payload, prompt_loader.load("ScEnsemble", settings.dataset), user_content=content)
        text = str(response.get("content", "")).strip().upper()
        letter = next((char for char in text if "A" <= char <= "Z"), "")
        return {"solution_letter": letter, "metadata": {"usage": usage}}

    def humaneval_sc_ensemble_adapter(payload):
        problem = _problem_from_payload(payload)
        candidates = tuple(payload.get("candidates", ()))
        labeled = "\n\n\n".join(
            f"{chr(65 + index)}: \n{candidate}" for index, candidate in enumerate(candidates)
        )
        prompt = prompt_loader.load("ScEnsemble", "HumanEval").format(
            problem=problem,
            solutions=labeled,
        )
        prompt = compile_sc_ensemble_xml_prompt(prompt)
        response, usage = _invoke_model(payload, "", user_content=prompt)
        letter = parse_solution_letter_xml(str(response.get("content", "")), len(candidates))
        return {"solution_letter": letter, "metadata": {"usage": usage}}

    def humaneval_reflection_adapter(payload):
        template = prompt_loader.load("TestReflection", "HumanEval")
        prompt = template.format(
            problem=payload.get("problem", ""),
            solution=payload.get("solution", ""),
            exec_pass=payload.get("exec_pass", ""),
            test_fail=payload.get("test_fail", ""),
        )
        filled = _humaneval_code_fill(payload, prompt, None)
        return {
            "reflection_and_solution": filled["solution"],
            "metadata": filled["metadata"],
        }

    def humaneval_fallback_adapter(payload):
        prompt = prompt_loader.load("ImproveCode", "HumanEval") + _problem_from_payload(payload)
        return _humaneval_code_fill(payload, prompt, _entrypoint_from_payload(payload))

    def programmer_code_adapter(payload):
        feedback = str(payload.get("feedback", "") or "").strip()
        attempt = payload.get("attempt", 1)
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            attempt = 1
        strict_programmer_instruction = (
            f"{programmer_instruction}\n\n"
            "Follow the required Python output contract exactly.\n"
            "Return only executable Python. Define def solve(): and call print(solve())."
        )
        if feedback:
            strict_programmer_instruction += (
                f"\n\nAttempt {attempt} of 3.\n"
                f"Previous response was rejected:\n{feedback}\n"
                "Return a complete corrected Python program. Do not repeat the rejected response."
            )
        response, usage = _invoke_model(
            payload,
            strict_programmer_instruction,
            user_content=_problem_from_payload(payload),
        )
        return {"code": response.get("content", ""), "metadata": {"usage": usage}}

    executor = CodeExecutor()
    def programmer_executor(payload):
        code = payload.get("code", "")
        result = executor.execute(str(code))
        if result.success:
            return result.stdout
        return {
            "success": False,
            "error": result.error or result.stderr or "program execution failed",
        }

    def bootstrap_programmer_adapter(payload):
        core = ProgrammerCore(generator=programmer_code_adapter, executor=programmer_executor, max_attempts=3)
        result = core.run(payload)
        metadata = {
            "attempts": result.get("attempts"),
            "attempt_diagnostics": result.get("attempt_diagnostics", []),
        }
        if result.get("error"):
            return {"operator_name": "Programmer", "status": "failed", "code": result.get("code"),
                    "execution_output": result.get("output"), "metadata": metadata}
        return {"operator_name": "Programmer", "status": "success", "solution": result.get("output"),
                "code": result.get("code"), "execution_output": result.get("output"),
                "metadata": metadata}
    humaneval_test_protocol = None
    if settings.dataset == "HumanEval":
        public_tests = HumanEvalPublicTestRepository(
            Path(__file__).parents[2] / "assets" / "data" / "humaneval_public_test.jsonl"
        )
        humaneval_test_protocol = HumanEvalTestProtocol(
            repository=public_tests,
            executor=SourceHumanEvalExecutor(timeout_seconds=15.0),
            reflection_adapter=humaneval_reflection_adapter,
            max_repairs=3,
        )

    for name, spec in registry.items():
        config = spec.setdefault("config", {})
        # Reuse existing Operator interfaces: ProgrammerGraph names its
        # injected generator ``programmer``; agent graphs use ``operator``.
        if settings.dataset == "HumanEval" and name in {"Generate", "GenerateCoT"}:
            config["operator"] = humaneval_generate_adapter
            config["instructions"] = ""
            config["raise_on_error"] = True
        elif settings.dataset == "HumanEval" and name == "MultiGenerateCoT":
            config["operator"] = humaneval_generate_adapter
            config["raise_on_error"] = True
        elif settings.dataset == "HumanEval" and name == "SelfRefine":
            config["operator"] = humaneval_self_refine_adapter
            config["instructions"] = ""
            config["raise_on_error"] = True
        elif settings.dataset == "HumanEval" and name == "ScEnsemble":
            config["operator"] = humaneval_sc_ensemble_adapter
            config["raise_on_error"] = True
        elif settings.dataset == "HumanEval" and name == "Test":
            config["protocol"] = humaneval_test_protocol
        elif name == "Programmer":
            config["code_generator"] = programmer_code_adapter
            config["executor"] = programmer_executor
        elif name == "GenerateCoT":
            config["operator"] = generate_cot_adapter
            config["instructions"] = prompt_loader.load(name, settings.dataset)
        elif name == "SelfRefine":
            config["operator"] = self_refine_adapter
            config["instructions"] = prompt_loader.load(name, settings.dataset)
        elif name == "ScEnsemble":
            config["operator"] = sc_ensemble_adapter
        elif name == "MultiGenerateCoT":
            config["operator"] = multi_generate_cot_adapter
        else:
            config["operator"] = adapter
            config["instructions"] = prompt_loader.load(name, settings.dataset)
    scorer = {"GSM8K": GSM8KScorer(), "MATH": MATHScorer(), "HumanEval": HumanEvalScorer()}[settings.dataset]
    optimizer = accumulator = None
    if settings.mode == "train":
        try:
            optimizer = torch.optim.Adam(controller.parameters(), lr=settings.learning_rate)
        except ImportError as exc: raise RuntimeError("training requires PyTorch") from exc
        accumulator = BatchAccumulator(optimizer, settings.batch_size)
    tracker = CostTracker(usage_manager)
    kwargs = dict(policy_controller=controller, operator_embeddings=embeddings, operator_catalog=catalog,
                  operator_registry=registry, dataset=settings.dataset, generate=bootstrap_generate_adapter, programmer=bootstrap_programmer_adapter,
                  scorer=scorer, cost_tracker=tracker, batch_accumulator=accumulator,
                  humaneval_test_protocol=humaneval_test_protocol,
                  humaneval_fallback=humaneval_fallback_adapter if settings.dataset == "HumanEval" else None,
                  graph_max_attempts=3 if settings.dataset == "HumanEval" else 1)
    root = build_train_root_graph(**kwargs) if settings.mode == "train" else build_test_root_graph(**kwargs)
    from .dataset_runner import DatasetRunner
    data_root = Path(__file__).parents[2] / "assets" / "data"
    loader = DatasetLoader(data_root)
    from dataclasses import asdict
    try:
        dataset = [asdict(x) for x in loader.load(settings.dataset, settings.split)]
    except FileNotFoundError:
        if settings.mode != "smoke":
            raise
        # Smoke mode is intentionally network- and data-independent.  Keep
        # the evaluator context shape identical to a real sample while using
        # a deterministic fixture when benchmark files are not installed.
        dataset = [{
            "problem_index": 0,
            "dataset": settings.dataset,
            "problem": "What is 6 multiplied by 7?",
            "expected_answer": "42",
            "entry_point": "",
            "test": None,
            "canonical_solution": None,
        }]
    if subset is not None:
        if isinstance(subset, bool) or not isinstance(subset, int) or subset <= 0:
            raise ValueError("subset must be a positive int")
        # A debug-only view of the dataset: the epoch bookkeeping stays
        # identical, the run just completes an epoch on fewer samples.
        dataset = dataset[:subset]
    runner = DatasetRunner(graph=root, dataset=dataset, epochs=settings.epochs,
                           batch_accumulator=accumulator, checkpoint_manager=checkpoint,
                           controller=controller if settings.mode == "train" else None,
                           optimizer=optimizer, operator_catalog=catalog,
                           artifact_store=artifact_store,
                           run_logger=run_logger,
                           run_config={"dataset": settings.dataset, "split": settings.split,
                                       "subset": subset,
                                       "mode": settings.mode, "sample": settings.sample,
                                       "batch_size": settings.batch_size, "epochs": settings.epochs,
                                       "seed": settings.seed, "model_name": settings.model.model_name,
                                       "embedding_model": settings.embedding_model,
                                       "run_id": output_root.name})
    return RuntimeContext(settings, model, embedder, controller, embeddings, tuple(catalog), registry, scorer, tracker, checkpoint, optimizer, accumulator, root, runner, artifact_store)

__all__ = ["RuntimeContext", "build_runtime"]
