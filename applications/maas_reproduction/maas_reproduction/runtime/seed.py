"""Reproducibility helpers."""
from __future__ import annotations
import random
def seed_everything(seed: int) -> None:
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0: raise ValueError("seed must be non-negative")
    random.seed(seed)
    try:
        import numpy as np; np.random.seed(seed)
    except ImportError: pass
    try:
        import torch; torch.manual_seed(seed); torch.cuda.manual_seed_all(seed) if torch.cuda.is_available() else None
    except ImportError: pass
__all__ = ["seed_everything"]
