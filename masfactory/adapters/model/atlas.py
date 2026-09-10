from __future__ import annotations

from .legacy_openai import LegacyOpenAIModel


class AtlasModel(LegacyOpenAIModel):
    """Atlas Cloud adapter using its OpenAI-compatible Chat Completions API."""

    BASE_URL = "https://api.atlascloud.ai/v1"
    DEFAULT_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"

    def __init__(
        self,
        api_key: str,
        model_name: str = DEFAULT_MODEL,
        invoke_settings: dict | None = None,
        capability_overrides: dict | None = None,
        **kwargs,
    ):
        # Generation requests are not safe to retry automatically.
        kwargs["max_retries"] = 0
        super().__init__(
            model_name=model_name,
            api_key=api_key,
            base_url=self.BASE_URL,
            invoke_settings=invoke_settings,
            capability_overrides=capability_overrides,
            **kwargs,
        )

    def invoke(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        settings: dict | None = None,
        **kwargs,
    ) -> dict:
        kwargs["max_retries"] = 1
        return super().invoke(messages, tools, settings, **kwargs)
