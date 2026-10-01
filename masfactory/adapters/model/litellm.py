from __future__ import annotations

import json
import time

from masfactory.adapters.token_usage_tracker import LiteLLMTokenCounter, TokenUsageTracker
from masfactory.core.multimodal import FieldModality, MediaMessageBlock, TextMessageBlock

from .base import Model, ModelCapabilities, ModelResponseType
from .common import (
    assistant_message_from_tool_calls,
    asset_to_data_url,
    build_capabilities,
    canonical_tool_calls,
    content_blocks,
    content_to_text,
    validate_media_capability,
)

_TRANSIENT_ERROR_NAMES = frozenset(
    {
        "APIConnectionError",
        "Timeout",
        "RateLimitError",
        "InternalServerError",
        "ServiceUnavailableError",
        "BadGatewayError",
    }
)


def _import_litellm():
    try:
        import litellm  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "LiteLLM support requires the 'litellm' package. "
            "Please install it with: pip install 'masfactory[litellm]'"
        ) from exc
    return litellm


def _is_transient_error(exc: BaseException) -> bool:
    module = type(exc).__module__ or ""
    return module.startswith("litellm") and type(exc).__name__ in _TRANSIENT_ERROR_NAMES


class LiteLLMModel(Model):
    """Model adapter backed by the LiteLLM SDK (100+ providers behind one Chat Completions API).

    `model_name` uses LiteLLM's `<provider>/<model>` routing, e.g. `anthropic/claude-sonnet-4-5`,
    `gemini/gemini-2.5-flash`, `bedrock/...`, `azure/<deployment>` or `ollama/llama3`. `base_url`
    is for routes that need an endpoint (Azure, Ollama, self-hosted vLLM).

    When `api_key` is omitted, LiteLLM reads the provider's own environment variables
    (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `AWS_*`, ...). Extra keyword arguments (for example
    `api_version`, `timeout` or `extra_headers`) are forwarded to every `litellm.completion` call.
    """

    def __init__(
        self,
        model_name: str,
        api_key: str | None = None,
        base_url: str | None = None,
        invoke_settings: dict | None = None,
        capability_overrides: dict | None = None,
        **kwargs,
    ):
        if model_name is None or model_name == "":
            raise ValueError("LiteLLM model_name is required.")
        litellm = _import_litellm()

        model_info = None
        try:
            model_info = litellm.get_model_info(model_name)
        except Exception:  # noqa: BLE001 - unknown/custom models are allowed
            model_info = None

        if model_info:
            image_input = bool(model_info.get("supports_vision"))
            pdf_input = bool(model_info.get("supports_pdf_input"))
        else:
            # Unknown to LiteLLM's model map (custom deployments): assume
            # OpenAI-style image input; users can declare PDF support via capability_overrides.
            image_input, pdf_input = True, False

        capabilities = build_capabilities(
            ModelCapabilities(
                image_input=image_input,
                pdf_input=pdf_input,
                image_sources=frozenset({"base64", "bytes", "path", "url"}),
                pdf_sources=frozenset({"base64", "bytes", "path"}),
            ),
            capability_overrides,
        )
        super().__init__(model_name, invoke_settings, capabilities=capabilities)

        self._litellm = litellm
        self._model_name = model_name
        self._api_key = api_key or None
        self._base_url = base_url or None
        # drop_params lets LiteLLM silently drop settings a provider does not accept
        # (e.g. `seed` or penalties on Anthropic) instead of failing the whole run.
        self._completion_kwargs = {"drop_params": True, **kwargs}

        self._token_tracker = TokenUsageTracker(
            model_name=model_name,
            api_key=self._api_key,
            base_url=self._base_url,
            counter=LiteLLMTokenCounter(model_name),
        )
        if model_info:
            self._description = {"id": model_name, "object": "model", **dict(model_info)}
        else:
            self._description = {"id": model_name, "object": "model"}

        self._settings_mapping = {
            "temperature": {"name": "temperature", "type": float, "section": [0.0, 2.0]},
            "max_tokens": {"name": "max_tokens", "type": int},
            "top_p": {"name": "top_p", "type": float, "section": [0.0, 1.0]},
            "stop": {"name": "stop", "type": list[str]},
            "tool_choice": {"name": "tool_choice", "type": (str, dict)},
            "presence_penalty": {"name": "presence_penalty", "type": float},
            "frequency_penalty": {"name": "frequency_penalty", "type": float},
            "seed": {"name": "seed", "type": int},
            "response_format": {"name": "response_format", "type": dict[str, object]},
        }

    def _connection_kwargs(self) -> dict:
        kwargs: dict = {}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._base_url:
            kwargs["api_base"] = self._base_url
        return kwargs

    def _encode_chat_content(self, content: object) -> str | list[dict]:
        if isinstance(content, str):
            return content
        encoded: list[dict] = []
        for block in content_blocks(content):
            if isinstance(block, str):
                encoded.append({"type": "text", "text": block})
                continue
            if isinstance(block, TextMessageBlock):
                encoded.append({"type": "text", "text": block.text})
                continue
            if isinstance(block, MediaMessageBlock):
                validate_media_capability(
                    provider="LiteLLM",
                    model_name=self.model_name,
                    capabilities=self.capabilities,
                    block=block,
                )
                asset = block.asset
                if asset.modality == FieldModality.PDF:
                    # LiteLLM translates OpenAI `file` parts to each provider's document format.
                    encoded.append({"type": "file", "file": {"file_data": asset_to_data_url(asset)}})
                    continue
                image_url = str(asset.value) if asset.source_kind == "url" else asset_to_data_url(asset)
                encoded.append({"type": "image_url", "image_url": {"url": image_url}})
                continue
            encoded.append({"type": "text", "text": str(block)})
        return encoded

    def _to_chat_messages(self, messages: list[dict]) -> list[dict]:
        chat_messages: list[dict] = []
        for message in messages:
            role = message.get("role")
            if role == "tool":
                chat_messages.append(
                    {
                        "role": "tool",
                        "content": content_to_text(message.get("content")),
                        "tool_call_id": message.get("tool_call_id"),
                    }
                )
                continue

            tool_calls = canonical_tool_calls(message)
            if role == "assistant" and tool_calls:
                chat_messages.append(
                    {
                        "role": "assistant",
                        "content": content_to_text(message.get("content")) or None,
                        "tool_calls": [
                            {
                                "id": tool_call.get("id"),
                                "type": "function",
                                "function": {
                                    "name": tool_call.get("name"),
                                    "arguments": json.dumps(tool_call.get("arguments", {}), ensure_ascii=False),
                                },
                            }
                            for tool_call in tool_calls
                        ],
                    }
                )
                continue

            chat_messages.append({"role": role, "content": self._encode_chat_content(message.get("content"))})
        return chat_messages

    def _parse_response(self, response) -> dict:
        result: dict = {}
        message = response.choices[0].message
        if message.tool_calls:
            tool_calls: list[dict] = []
            result["type"] = ModelResponseType.TOOL_CALL
            assistant_content = message.content or ""
            for tool_call in message.tool_calls:
                arguments = tool_call.function.arguments
                if isinstance(arguments, str):
                    arguments = json.loads(arguments) if arguments.strip() else {}
                tool_calls.append(
                    {
                        "id": tool_call.id,
                        "name": tool_call.function.name,
                        "arguments": arguments or {},
                    }
                )
            result["content"] = tool_calls
            result["assistant_message"] = assistant_message_from_tool_calls(tool_calls, assistant_content)
            result["raw_response"] = response
        elif message.content:
            result["type"] = ModelResponseType.CONTENT
            result["content"] = message.content
            result["raw_response"] = response
        else:
            raise ValueError("Response is not valid")

        usage = getattr(response, "usage", None)
        if usage:
            self._token_tracker.accumulate(
                input_usage=getattr(usage, "prompt_tokens", 0) or 0,
                output_usage=getattr(usage, "completion_tokens", 0) or 0,
            )
        return result

    def invoke(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        settings: dict | None = None,
        **kwargs,
    ) -> dict:
        tools_dict = [{"type": "function", "function": tool} for tool in tools] if tools else None
        max_retries = kwargs.pop("max_retries", 3)
        base_delay = kwargs.pop("retry_base_delay", 1.0)

        request: dict = {
            "model": self.model_name,
            "messages": self._to_chat_messages(messages),
            **self._connection_kwargs(),
            **self._completion_kwargs,
            **self._parse_settings(settings),
            **kwargs,
        }
        if tools_dict:
            request["tools"] = tools_dict

        for attempt in range(max(1, max_retries)):
            try:
                response = self._litellm.completion(**request)
                return self._parse_response(response)
            except Exception as exc:  # noqa: BLE001
                # Only transient provider/network failures are retried; auth, validation and
                # context-window errors surface immediately.
                if not _is_transient_error(exc) or attempt >= max_retries - 1:
                    raise
                time.sleep(base_delay * (2 ** attempt))
        raise RuntimeError("LiteLLMModel.invoke failed without specific exception")

    def generate_images(
        self,
        prompt: str,
        model: str = None,
        n: int = 1,
        quality: str = "standard",
        response_format: str = "url",
        size: str = "1024x1024",
        style: str = "vivid",
        user: str = None,
        **kwargs,
    ) -> list[dict]:
        api_params = {"prompt": prompt, "model": model or self.model_name, "n": n, "size": size}
        if quality != "standard":
            api_params["quality"] = quality
        if response_format != "url":
            api_params["response_format"] = response_format
        if style != "vivid":
            api_params["style"] = style
        if user is not None:
            api_params["user"] = user
        api_params.update(self._connection_kwargs())
        api_params.update(kwargs)

        response = self._litellm.image_generation(**api_params)
        images: list[dict] = []
        for img_data in response.data:
            img_dict: dict = {}
            if getattr(img_data, "url", None):
                img_dict["url"] = img_data.url
            if getattr(img_data, "b64_json", None):
                img_dict["b64_json"] = img_data.b64_json
            if getattr(img_data, "revised_prompt", None):
                img_dict["revised_prompt"] = img_data.revised_prompt
            images.append(img_dict)
        return images
