"""Lazy, frozen embedding providers."""
from __future__ import annotations
from typing import Sequence, Any

class EmbeddingProvider:
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2", device: str = "cpu"):
        self.model_name, self.device, self._model = model_name, device, None
    def _load(self):
        if self._model is None:
            try: from sentence_transformers import SentenceTransformer
            except ImportError as exc: raise ImportError("install embeddings dependencies") from exc
            self._model = SentenceTransformer(self.model_name, device=self.device); self._model.eval()
        return self._model
    def encode(self, text: str) -> Any: return self._load().encode(text, convert_to_tensor=True, normalize_embeddings=False)
    def encode_many(self, texts: Sequence[str]) -> Any: return self._load().encode(list(texts), convert_to_tensor=True, normalize_embeddings=False)

class FakeEmbeddingProvider:
    def __init__(self, dimension: int = 384): self.dimension = dimension
    def encode(self, text: str):
        value = (sum(map(ord, text)) % 997) / 997.0
        try:
            import torch; return torch.full((self.dimension,), value)
        except ImportError:
            import numpy as np; return np.full((self.dimension,), value, dtype="float32")
    def encode_many(self, texts: Sequence[str]):
        try:
            import torch; return torch.stack([self.encode(t) for t in texts])
        except ImportError:
            import numpy as np; return np.stack([self.encode(t) for t in texts])

__all__ = ["EmbeddingProvider", "FakeEmbeddingProvider"]
