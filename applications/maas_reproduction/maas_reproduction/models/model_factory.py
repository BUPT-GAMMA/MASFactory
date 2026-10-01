"""Single shared MASFactory Model factory."""
from __future__ import annotations
import os
from .fake_model import FakeModel
from ..runtime.settings import ModelSettings

def create_shared_model(settings: ModelSettings, *, fake: bool = False):
    if fake: return FakeModel()
    provider = settings.provider.lower()
    if provider not in {"openai", "deepseek"}:
        raise ValueError(f"unsupported provider: {settings.provider}")
    key = os.getenv(settings.api_key_env)
    if not key: raise RuntimeError(f"missing API key environment variable: {settings.api_key_env}")
    # DeepSeek serves Chat Completions only; OpenAIModel speaks the Responses
    # API exclusively, so it cannot reach a DeepSeek endpoint.
    if provider == "deepseek":
        from masfactory.adapters.model.legacy_openai import LegacyOpenAIModel as ModelClass
    else:
        from masfactory.adapters.model.openai import OpenAIModel as ModelClass
    kwargs = {"model_name": settings.model_name, "api_key": key, "invoke_settings": {"temperature": settings.temperature, "max_tokens": settings.max_tokens}}
    if settings.base_url_env and os.getenv(settings.base_url_env): kwargs["base_url"] = os.getenv(settings.base_url_env)
    return ModelClass(**kwargs)

__all__ = ["create_shared_model"]
