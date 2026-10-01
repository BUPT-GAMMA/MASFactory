"""Local JSONL dataset loader with one normalized sample interface."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

@dataclass(frozen=True)
class DatasetSample:
    problem_index: int
    dataset: str
    problem: str
    expected_answer: Any
    entry_point: str = ""
    test: str | None = None
    canonical_solution: str | None = None

class DatasetLoader:
    def __init__(self, data_root: str | Path): self.data_root = Path(data_root)
    def load(self, dataset: str, split: str, indices: Sequence[int] | None = None) -> list[DatasetSample]:
        if dataset not in {"GSM8K", "MATH", "HumanEval"}: raise ValueError("unsupported dataset")
        if split not in {"train", "test"}: raise ValueError("split must be train or test")
        path = self.data_root / f"{dataset.lower()}_{split}.jsonl"
        if not path.exists(): raise FileNotFoundError(path)
        wanted = set(indices) if indices is not None else None
        if wanted is not None and any(i < 0 for i in wanted): raise IndexError("indices must be non-negative")
        result=[]
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            if not line.strip(): continue
            raw=json.loads(line); idx=int(raw.get("problem_index", raw.get("index", line_no)))
            if wanted is not None and idx not in wanted: continue
            problem=raw.get("problem", raw.get("question", raw.get("prompt")))
            if not isinstance(problem,str) or not problem.strip(): raise ValueError(f"missing problem at {line_no}")
            expected=raw.get("expected_answer", raw.get("answer", raw.get("solution", raw.get("canonical_solution"))))
            if dataset == "HumanEval" and not raw.get("entry_point"): raise ValueError("HumanEval entry_point is required")
            result.append(DatasetSample(idx,dataset,problem,expected,str(raw.get("entry_point", "")),raw.get("test"),raw.get("canonical_solution")))
        if wanted is not None and {x.problem_index for x in result} != wanted: raise IndexError("requested index not found")
        return result

__all__ = ["DatasetSample", "DatasetLoader"]
