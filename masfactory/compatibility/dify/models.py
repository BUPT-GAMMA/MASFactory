"""Map Dify `model` blocks to MASFactory `Model` adapters (real API by default)."""

from __future__ import annotations

import os
from typing import Any

from masfactory.adapters.model import Model
from masfactory.adapters.model.openai import OpenAIModel

from masfactory.compatibility.errors import CompatibilityImportError

_NON_OPENAI_SDK_PROVIDERS = frozenset(
    {"anthropic", "google", "gemini", "vertex_ai", "bedrock", "cohere", "azure"}
)


def openai_compatible_model_from_dify(
    model_config: dict[str, Any],
    *,
    api_key: str | None = None,
    base_url: str | None = None,
) -> Model:
    """Build an `OpenAIModel` from a Dify node `model` dict."""
    # Dify exports namespaced ids such as `langgenius/anthropic/anthropic`.
    prov = str(model_config.get("provider") or "openai").lower().rsplit("/", 1)[-1]
    if prov in _NON_OPENAI_SDK_PROVIDERS:
        raise CompatibilityImportError(
            f"Dify LLM provider {model_config.get('provider')!r} needs a dedicated adapter. "
            "Pass `DifyCompileOptions(model_factory=...)`, e.g. `model_factory=litellm_model_from_dify`."
        )

    key = api_key if api_key not in (None, "") else os.getenv("OPENAI_API_KEY")
    if not key:
        raise CompatibilityImportError(
            "Real Dify LLM execution requires `OPENAI_API_KEY` or "
            "`DifyCompileOptions(openai_api_key=...)` / `use_stub_llm=True` for tests."
        )

    url = base_url if base_url not in (None, "") else (
        os.getenv("OPENAI_BASE_URL") or os.getenv("BASE_URL") or None
    )
    if url == "":
        url = None

    name = model_config.get("name") or os.getenv("OPENAI_MODEL_NAME") or "gpt-4o-mini"
    completion = model_config.get("completion_params")
    invoke_settings = dict(completion) if isinstance(completion, dict) else None

    return OpenAIModel(
        model_name=str(name),
        api_key=api_key or None,
        base_url=base_url or None,
        invoke_settings=invoke_settings,
    )


# Dify provider id (last segment of e.g. `langgenius/anthropic/anthropic`) -> LiteLLM route prefix.
_DIFY_TO_LITELLM_PROVIDER = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "gemini",
    "gemini": "gemini",
    "vertex_ai": "vertex_ai",
    "bedrock": "bedrock",
    "cohere": "cohere",
    "azure": "azure",
    "azure_openai": "azure",
    "mistralai": "mistral",
    "deepseek": "deepseek",
    "groq": "groq",
    "ollama": "ollama",
    "openrouter": "openrouter",
    "tongyi": "dashscope",
    "zhipuai": "zai",
    "moonshot": "moonshot",
    "togetherai": "together_ai",
}


def litellm_model_from_dify(
    model_config: dict[str, Any],
    *,
    api_key: str | None = None,
    base_url: str | None = None,
) -> Model:
    """Build a `LiteLLMModel` from a Dify node `model` dict, for any provider LiteLLM supports.

    Use it as `DifyCompileOptions(model_factory=litellm_model_from_dify)` to import workflows whose
    LLM nodes target Anthropic, Gemini, Vertex AI, Bedrock, Cohere, Azure, ... Credentials come from
    each provider's usual environment variables unless `api_key` is passed; `base_url` is for routes
    that need an endpoint (Azure, Ollama, self-hosted vLLM).
    """
    from masfactory.adapters.model.litellm import LiteLLMModel

    name = str(model_config.get("name") or "").strip()
    if not name:
        raise CompatibilityImportError("Dify LLM node is missing a model `name`.")

    raw_provider = str(model_config.get("provider") or "").strip().lower()
    provider = raw_provider.rsplit("/", 1)[-1]
    if not provider or ("/" in name and name.split("/", 1)[0] in _DIFY_TO_LITELLM_PROVIDER.values()):
        model_name = name
    else:
        prefix = _DIFY_TO_LITELLM_PROVIDER.get(provider, provider)
        model_name = f"{prefix}/{name}"

    completion = model_config.get("completion_params")
    invoke_settings = dict(completion) if isinstance(completion, dict) else None

    return LiteLLMModel(
        model_name=model_name,
        api_key=api_key or None,
        base_url=base_url or None,
        invoke_settings=invoke_settings,
    )
