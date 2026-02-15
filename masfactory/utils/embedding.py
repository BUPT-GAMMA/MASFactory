from typing import Callable, Dict, List, Union, Optional
import importlib.util
import numpy as np
import os
import json
import re
from abc import ABC, abstractmethod

# Optional dependency availability flags (backward-compatible with earlier versions).
OPENAI_AVAILABLE = importlib.util.find_spec("openai") is not None
SENTENCE_TRANSFORMERS_AVAILABLE = importlib.util.find_spec("sentence_transformers") is not None
ANTHROPIC_AVAILABLE = importlib.util.find_spec("anthropic") is not None
SKLEARN_AVAILABLE = importlib.util.find_spec("sklearn") is not None

class BaseEmbedder(ABC):
    """Abstract embedder interface.

    Implementations return a callable that maps text to an `np.ndarray` embedding vector.
    """

    def __init__(self):
        pass
    
    @abstractmethod
    def get_embedding_function(self) -> Callable[[str], np.ndarray]:
        """Return a callable that maps text to an embedding vector."""
        pass
    
class TfidfEmbedder(BaseEmbedder):
    """TF-IDF embedder backed by scikit-learn."""

    def __init__(self, documents: List[str] = None, max_features: int = 5000):
        """Create a TF-IDF embedder.

        Args:
            documents: Optional seed documents used to fit the vectorizer.
            max_features: Maximum vocabulary size.
        """
        super().__init__()
        
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
        except ImportError:
            raise ImportError("scikit-learn is not installed. Please install it using 'pip install scikit-learn'")
        
        self.documents = documents or []
        self.max_features = max_features
        
        self.vectorizer = TfidfVectorizer(max_features=max_features)
        
        if self.documents:
            try:
                self.vectorizer.fit(self.documents)
            except ValueError as e:
                # sklearn default token_pattern ignores 1-char tokens, which can yield an empty vocabulary
                # for corpora like ["a b", "a c"]. Retry with a more permissive token_pattern.
                if "empty vocabulary" not in str(e).lower():
                    raise
                self.vectorizer = TfidfVectorizer(
                    max_features=max_features,
                    token_pattern=r"(?u)\b\w+\b",
                )
                self.vectorizer.fit(self.documents)

    def get_embedding_function(self) -> Callable[[str], np.ndarray]:
        def embedding_function(text: str) -> np.ndarray:
            vector = self.vectorizer.transform([text]).toarray()[0]
            
            return vector
        
        return embedding_function

class BagOfWordsEmbedder(BaseEmbedder):
    """Bag-of-words embedder backed by scikit-learn."""

    def __init__(self, documents: List[str] = None, max_features: int = 5000):
        """Create a bag-of-words embedder.

        Args:
            documents: Optional seed documents used to fit the vectorizer.
            max_features: Maximum vocabulary size.
        """
        super().__init__()
        
        try:
            from sklearn.feature_extraction.text import CountVectorizer
        except ImportError:
            raise ImportError("scikit-learn is not installed. Please install it using 'pip install scikit-learn'")
        
        self.documents = documents or []
        self.max_features = max_features
        
        self.vectorizer = CountVectorizer(max_features=max_features)
        
        if self.documents:
            try:
                self.vectorizer.fit(self.documents)
            except ValueError as e:
                if "empty vocabulary" not in str(e).lower():
                    raise
                self.vectorizer = CountVectorizer(
                    max_features=max_features,
                    token_pattern=r"(?u)\b\w+\b",
                )
                self.vectorizer.fit(self.documents)
    
    def get_embedding_function(self) -> Callable[[str], np.ndarray]:
        def embedding_function(text: str) -> np.ndarray:            
            vector = self.vectorizer.transform([text]).toarray()[0]
            
            return vector
        
        return embedding_function

class SentenceTransformerEmbedder(BaseEmbedder):
    """Embedder backed by `sentence-transformers`."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """Create a sentence-transformers embedder.

        Args:
            model_name: SentenceTransformer model identifier.
        """
        super().__init__()
        
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError("sentence-transformers is not installed. Please install it using 'pip install sentence-transformers'")
        
        self.model_name = model_name
        
        self.model = SentenceTransformer(model_name)
    
    def get_embedding_function(self) -> Callable[[str], np.ndarray]:
        def embedding_function(text: str) -> np.ndarray:
            embedding = self.model.encode(text)
            
            return embedding
        
        return embedding_function

class OpenAIEmbedder(BaseEmbedder):
    """Embedder backed by the OpenAI embeddings API."""

    def __init__(self, model: str = "text-embedding-3-small", api_key: str = None, **kwargs):
        """Create an OpenAI embedder.

        Args:
            model: Embedding model identifier.
            api_key: Optional OpenAI API key.
            **kwargs: Extra kwargs forwarded to the OpenAI client constructor.
        """
        super().__init__()
        
        try:
            import openai
        except ImportError:
            raise ImportError("openai is not installed. Please install it using 'pip install openai'")
        
        self.model = model
        
        self.client = openai.OpenAI(api_key=api_key, **kwargs)
    
    def get_embedding_function(self) -> Callable[[str], np.ndarray]:
        def embedding_function(text: str) -> np.ndarray:
            try:
                response = self.client.embeddings.create(
                    model=self.model,
                    input=text
                )
                embedding = np.array(response.data[0].embedding)
                
                return embedding
            except Exception as e:
                raise RuntimeError(f"Failed to generate OpenAI embedding: {e}") from e
        
        return embedding_function

class AnthropicEmbedder(BaseEmbedder):
    """Placeholder embedder for Anthropic.

    The official Anthropic SDK does not expose a general embeddings API.
    """

    def __init__(self, api_key: str = None, model: str = "claude-3-haiku-20240307", **kwargs):
        """Create an Anthropic embedder placeholder.

        Args:
            api_key: Optional Anthropic API key.
            model: Model identifier (kept for API symmetry).
            **kwargs: Extra kwargs forwarded to the Anthropic client constructor.
        """
        super().__init__()
        
        try:
            from anthropic import Anthropic
        except ImportError:
            raise ImportError("anthropic is not installed. Please install it using 'pip install anthropic'")
        
        self.model = model
        
        self.client = Anthropic(api_key=api_key, **kwargs)
    
    def get_embedding_function(self) -> Callable[[str], np.ndarray]:
        def embedding_function(text: str) -> np.ndarray:
            raise NotImplementedError(
                "Anthropic does not expose a general embeddings API in the official SDK. "
                "Use OpenAIEmbedder / SentenceTransformerEmbedder / TfidfEmbedder instead."
            )
        
        return embedding_function

class HybridEmbedder(BaseEmbedder):
    """Embedder that combines multiple embedders into one vector."""

    def __init__(self, embedders: List[BaseEmbedder], weights: List[float] = None):
        """Create a HybridEmbedder.

        Args:
            embedders: List of embedders to combine.
            weights: Optional weights aligned with `embedders`.
        """
        super().__init__()
        
        self.embedders = embedders
        
        if weights is None:
            self.weights = [1.0 / len(embedders)] * len(embedders)
        else:
            self.weights = weights
        
        if len(self.weights) != len(self.embedders):
            raise ValueError("Number of weights must match number of embedders")
        
        self.embedding_functions = [embedder.get_embedding_function() for embedder in embedders]
    
    def get_embedding_function(self) -> Callable[[str], np.ndarray]:
        """Return a callable that produces a combined embedding vector."""
        def embedding_function(text: str) -> np.ndarray:
            embeddings = []
            embedding_dims = []
            
            for func in self.embedding_functions:
                embedding = func(text)
                embeddings.append(embedding)
                embedding_dims.append(len(embedding))
            
            # combined = np.concatenate(embeddings)
            
            normalized_embeddings = []
            for i, emb in enumerate(embeddings):
                norm_emb = emb / np.linalg.norm(emb)
                weighted_emb = norm_emb * self.weights[i]
                normalized_embeddings.append(weighted_emb)
            
            combined_dict = {}
            for i, emb in enumerate(normalized_embeddings):
                for j, val in enumerate(emb):
                    combined_dict[f"emb{i}_dim{j}"] = val
            
            combined = np.array(list(combined_dict.values()))
            
            return combined
        
        return embedding_function

class SimpleEmbedder(BaseEmbedder):
    """Very simple hashing-based embedder.

    This is intended for lightweight demos and tests, not for high-quality retrieval.
    """

    def __init__(self, vocab_size: int = 10000):
        """Create a SimpleEmbedder.

        Args:
            vocab_size: Size of the hashing vocabulary / embedding dimension.
        """
        super().__init__()
        
        self.vocab_size = vocab_size

    def get_embedding_function(self) -> Callable[[str], np.ndarray]:
        def embedding_function(text: str) -> np.ndarray:
            embedding = np.zeros(self.vocab_size)
            
            for char in text:
                hash_val = hash(char) % self.vocab_size
                embedding[hash_val] += 1
            
            if np.sum(embedding) > 0:
                embedding = embedding / np.sum(embedding)
            
            return embedding
        
        return embedding_function
