"""Token counting utilities and usage tracker for multiple model providers."""
from __future__ import annotations
from typing import Optional
from abc import ABC, abstractmethod
import tiktoken

class TokenCounter(ABC):
    """Abstract token counter interface."""
    
    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Count tokens for plain text."""
        pass
    
    @abstractmethod
    def count_message_tokens(self, messages: list[dict]) -> int:
        """Count tokens for chat-style message lists."""
        pass

class OpenAITokenCounter(TokenCounter):
    """OpenAI-family token counter based on `tiktoken`."""
    
    def __init__(self, model_name: str):
        """Create an OpenAI token counter.

        Args:
            model_name: Model identifier used to select a suitable `tiktoken` encoding.
        """
        self.model_name = model_name
        self.encoding = self._get_encoding()
    
    def _get_encoding(self):
        try:
            return tiktoken.encoding_for_model(self.model_name)
        except KeyError:
            model = self.model_name.lower()
            if model.startswith("gpt-5"):
                return tiktoken.get_encoding("o200k_base")
            if model.startswith("gpt-4o"):
                return tiktoken.get_encoding("o200k_base")
            
            if model.startswith(("gpt-4", "gpt-3.5")):
                return tiktoken.get_encoding("cl100k_base")
            
            if model.startswith(("text-davinci", "text-curie", "text-babbage", "text-ada")):
                return tiktoken.get_encoding("p50k_base")
            if model in ("davinci", "curie", "babbage", "ada"):
                return tiktoken.get_encoding("p50k_base")
            
            if model.startswith("code-"):
                return tiktoken.get_encoding("p50k_base")
            
            if model.startswith("text-embedding"):
                return tiktoken.get_encoding("cl100k_base")
            
            if model.startswith("dall-e"):
                return tiktoken.get_encoding("cl100k_base")
            
            return tiktoken.get_encoding("cl100k_base")
    
    def count_tokens(self, text: str) -> int:
        return len(self.encoding.encode(text))
    
    def count_message_tokens(self, messages: list[dict]) -> int:
        num_tokens = 0
        for message in messages:
            num_tokens += 3
            for key, value in message.items():
                if isinstance(value, str):
                    num_tokens += self.count_tokens(value)
                if key == "name":
                    num_tokens += 1
        num_tokens += 3
        return num_tokens

class AnthropicTokenCounter(TokenCounter):
    """Anthropic token counter using Anthropic SDK."""
    
    def __init__(self, model_name: str, api_key: Optional[str] = None, base_url: Optional[str] = None):
        """Create an Anthropic token counter.

        Args:
            model_name: Model identifier.
            api_key: Optional API key used by the Anthropic SDK.
            base_url: Optional custom base URL for the Anthropic API.
        """
        self.model_name = model_name
        self._client = None
        self._api_key = api_key
        self._base_url = base_url
    
    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
                kwargs = {"api_key": self._api_key}
                if self._base_url:
                    kwargs["base_url"] = self._base_url
                self._client = anthropic.Anthropic(**kwargs)
            except ImportError:
                raise ImportError("Please install anthropic: pip install anthropic")
        return self._client
    
    def count_tokens(self, text: str) -> int:
        client = self._get_client()
        return client.count_tokens(text)
    
    def count_message_tokens(self, messages: list[dict]) -> int:
        total = 0
        for msg in messages:
            if "content" in msg:
                content = msg["content"]
                if isinstance(content, str):
                    total += self.count_tokens(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and "text" in block:
                            total += self.count_tokens(block["text"])
            if "role" in msg:
                total += self.count_tokens(msg["role"])
        return total

class GeminiTokenCounter(TokenCounter):
    """Gemini token counter with SDK-first and local fallback behavior."""
    
    def __init__(self, model_name: str, api_key: Optional[str] = None, base_url: Optional[str] = None):
        """Create a Gemini token counter.

        Args:
            model_name: Model identifier.
            api_key: Optional API key used by the Gemini SDK.
            base_url: Optional custom base URL for the Gemini API.
        """
        self.model_name = model_name
        self._client = None
        self._api_key = api_key
        self._base_url = base_url
        self._fallback = None
    
    def _get_client(self):
        if self._client is None:
            try:
                from google import genai
                from google.genai import types

                http_options = (
                    types.HttpOptions(base_url=self._base_url) if self._base_url else None
                )
                self._client = genai.Client(api_key=self._api_key, http_options=http_options)
            except Exception:
                self._client = None
        return self._client
    
    def count_tokens(self, text: str) -> int:
        if self._fallback is None:
            self._fallback = DefaultTokenCounter(self.model_name)
        client = self._get_client()
        if client is None:
            return self._fallback.count_tokens(text)
        try:
            resp = client.models.count_tokens(model=self.model_name, contents=text)
            return int(resp.total_tokens or 0)
        except Exception:
            return self._fallback.count_tokens(text)
    
    def count_message_tokens(self, messages: list[dict]) -> int:
        if self._fallback is None:
            self._fallback = DefaultTokenCounter(self.model_name)
        client = self._get_client()
        if client is None:
            return self._fallback.count_message_tokens(messages)
        try:
            contents: list[str] = []
            for msg in messages:
                content = msg.get("content", "")
                if content is None:
                    content = ""
                elif not isinstance(content, str):
                    content = str(content)
                contents.append(content)
            resp = client.models.count_tokens(model=self.model_name, contents=contents)
            return int(resp.total_tokens or 0)
        except Exception:
            return self._fallback.count_message_tokens(messages)

class HuggingFaceTokenCounter(TokenCounter):
    """HuggingFace tokenizer-based counter for mapped model names."""
    
    _MODEL_TO_HF_ID = {
        "llama-3.2-90b": "meta-llama/Llama-3.2-90B",
        "llama-3.2-11b": "meta-llama/Llama-3.2-11B",
        "llama-3.2-3b": "meta-llama/Llama-3.2-3B",
        "llama-3.2-1b": "meta-llama/Llama-3.2-1B",
        "llama-3.1-405b": "meta-llama/Meta-Llama-3.1-405B",
        "llama-3.1-70b": "meta-llama/Meta-Llama-3.1-70B",
        "llama-3.1-8b": "meta-llama/Meta-Llama-3.1-8B",
        "llama-3-70b": "meta-llama/Meta-Llama-3-70B",
        "llama-3-8b": "meta-llama/Meta-Llama-3-8B",
        "llama-2-70b": "meta-llama/Llama-2-70b-hf",
        "llama-2-13b": "meta-llama/Llama-2-13b-hf",
        "llama-2-7b": "meta-llama/Llama-2-7b-hf",
        
        "mistral-7b": "mistralai/Mistral-7B-v0.1",
        "mixtral-8x7b": "mistralai/Mixtral-8x7B-v0.1",
        "mixtral-8x22b": "mistralai/Mixtral-8x22B-v0.1",
        
        "qwen-7b": "Qwen/Qwen-7B",
        "qwen-14b": "Qwen/Qwen-14B",
        "qwen-72b": "Qwen/Qwen-72B",
        "qwen2-72b": "Qwen/Qwen2-72B",
        "qwen2.5-72b": "Qwen/Qwen2.5-72B",
        "qwen2.5-7b": "Qwen/Qwen2.5-7B",
        
        "chatglm3-6b": "THUDM/chatglm3-6b",
        "chatglm2-6b": "THUDM/chatglm2-6b",
        
        "yi-34b": "01-ai/Yi-34B",
        "yi-6b": "01-ai/Yi-6B",
        "yi-34b-chat": "01-ai/Yi-34B-Chat",
        "yi-6b-chat": "01-ai/Yi-6B-Chat",
        
        "falcon-180b": "tiiuae/falcon-180B",
        "falcon-40b": "tiiuae/falcon-40b",
        "falcon-7b": "tiiuae/falcon-7b",
        
        "vicuna-13b": "lmsys/vicuna-13b-v1.5",
        "vicuna-7b": "lmsys/vicuna-7b-v1.5",
        
        "bloom-176b": "bigscience/bloom",
        "bloomz-176b": "bigscience/bloomz",
        
        "stablelm-tuned-alpha-7b": "stabilityai/stablelm-tuned-alpha-7b",
        "stablelm-base-alpha-7b": "stabilityai/stablelm-base-alpha-7b",
        
        "deepseek-coder-6.7b": "deepseek-ai/deepseek-coder-6.7b-base",
        "deepseek-coder-33b": "deepseek-ai/deepseek-coder-33b-base",
        "deepseek-llm-7b": "deepseek-ai/deepseek-llm-7b-base",
        "deepseek-llm-67b": "deepseek-ai/deepseek-llm-67b-base",
        
        "command-r": "CohereForAI/c4ai-command-r-v01",
        "command-r-plus": "CohereForAI/c4ai-command-r-plus",
    }
    
    def __init__(self, model_name: str):
        """Create a HuggingFace token counter.

        Args:
            model_name: Model identifier used to map to a HuggingFace tokenizer.
        """
        self.model_name = model_name
        self._tokenizer = None
    
    def _get_tokenizer(self):
        if self._tokenizer is None:
            try:
                from transformers import AutoTokenizer
                hf_id = self._MODEL_TO_HF_ID.get(self.model_name)
                if not hf_id:
                    raise ValueError(f"No HuggingFace mapping found for model: {self.model_name}")
                self._tokenizer = AutoTokenizer.from_pretrained(hf_id)
            except ImportError:
                raise ImportError("Please install transformers: pip install transformers")
        return self._tokenizer
    
    def count_tokens(self, text: str) -> int:
        tokenizer = self._get_tokenizer()
        return len(tokenizer.encode(text))
    
    def count_message_tokens(self, messages: list[dict]) -> int:
        total = 0
        for msg in messages:
            if "content" in msg and isinstance(msg["content"], str):
                total += self.count_tokens(msg["content"])
            if "role" in msg:
                total += self.count_tokens(msg["role"])
        return total

class DefaultTokenCounter(TokenCounter):
    """Fallback token counter using `cl100k_base`."""
    
    def __init__(self, model_name: str):
        """Create a fallback token counter.

        Args:
            model_name: Model identifier (kept for API symmetry).
        """
        self.model_name = model_name
        self.encoding = tiktoken.get_encoding("cl100k_base")
    
    def count_tokens(self, text: str) -> int:
        return len(self.encoding.encode(text))
    
    def count_message_tokens(self, messages: list[dict]) -> int:
        total = 0
        for msg in messages:
            if "content" in msg and isinstance(msg["content"], str):
                total += self.count_tokens(msg["content"])
            if "role" in msg:
                total += self.count_tokens(msg["role"])
        return total

class TokenUsageTracker:
    """Factory-backed token usage accumulator."""
    
    def __init__(self, model_name: str, api_key: Optional[str] = None, base_url: Optional[str] = None):
        """Create a TokenUsageTracker.

        Args:
            model_name: Model identifier used to select provider-specific counting logic.
            api_key: Optional API key passed to provider SDKs when needed for counting endpoints.
            base_url: Optional custom base URL passed to provider SDKs.
        """
        self.model_name = model_name
        self.provider = self._detect_provider(model_name)
        self._counter = self._create_counter(model_name, self.provider, api_key, base_url)
        self._total_input_usage = 0
        self._total_output_usage = 0
    
    @staticmethod
    def _detect_provider(model_name: str) -> str:
        """Infer model provider from model name."""
        name = model_name.lower()
        if any(p in name for p in ["gpt-", "text-", "davinci", "curie", "babbage", "ada", "code-", "dall-e"]):
            return "openai"
        if "claude" in name:
            return "anthropic"
        if "gemini" in name or "imagen" in name:
            return "gemini"
        if any(p in name for p in [
            "llama", "mistral", "mixtral", "qwen-7b", "qwen-14b", "qwen-72b", 
            "qwen2", "chatglm", "yi-", "falcon", "vicuna", "bloom", "stablelm", "deepseek-coder", "deepseek-llm", "command-r"
        ]):
            return "huggingface"
        return "default"
    
    @staticmethod
    def _create_counter(model_name: str, provider: str, api_key: Optional[str], base_url: Optional[str]) -> TokenCounter:
        """Create provider-specific token counter."""
        if provider == "openai":
            return OpenAITokenCounter(model_name)
        elif provider == "anthropic":
            return AnthropicTokenCounter(model_name, api_key, base_url)
        elif provider == "gemini":
            return GeminiTokenCounter(model_name, api_key, base_url)
        elif provider == "huggingface":
            return HuggingFaceTokenCounter(model_name)
        else:
            return DefaultTokenCounter(model_name)
    
    @property
    def total_input_usage(self) -> int:
        return self._total_input_usage
    
    @property
    def total_output_usage(self) -> int:
        return self._total_output_usage
    
    @property
    def total_usage(self) -> int:
        return self._total_input_usage + self._total_output_usage
    
    def count_tokens(self, text: str) -> int:
        return self._counter.count_tokens(text)
    
    def count_message_tokens(self, messages: list[dict]) -> int:
        return self._counter.count_message_tokens(messages)
    
    def accumulate(self, input_usage: int, output_usage: int):
        self._total_input_usage += input_usage
        self._total_output_usage += output_usage
    
    def reset(self):
        self._total_input_usage = 0
        self._total_output_usage = 0
