from __future__ import annotations

import json
import time

from openai import OpenAI

from masfactory.adapters.token_usage_tracker import TokenUsageTracker
from masfactory.core.multimodal import FieldModality, MediaMessageBlock, TextMessageBlock

from .base import Model, ModelCapabilities, ModelResponseType
from .common import (
    assistant_message_from_tool_calls,
    asset_to_base64,
    asset_to_data_url,
    build_capabilities,
    canonical_tool_calls,
    content_blocks,
    content_to_text,
    extract_openai_response_text,
    validate_media_capability,
)


class OpenAIModel(Model):
    """OpenAI model adapter using the Responses API only."""

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str | None = None,
        invoke_settings: dict | None = None,
        capability_overrides: dict | None = None,
        **kwargs,
    ):
        capabilities = build_capabilities(
            ModelCapabilities(
                image_input=True,
                pdf_input=True,
            ),
            capability_overrides,
        )
        super().__init__(model_name, invoke_settings, capabilities=capabilities, **kwargs)

        if api_key is None or api_key == "":
            raise ValueError("OpenAI api_key is required.")
        if model_name is None or model_name == "":
            raise ValueError("OpenAI model_name is required.")

        client_kwargs = dict(kwargs)
        if base_url:
            client_kwargs["base_url"] = base_url

        self._client = OpenAI(api_key=api_key, **client_kwargs)
        self._model_name = model_name
        self._token_tracker = TokenUsageTracker(model_name=model_name, api_key=api_key, base_url=base_url)
        try:
            model_info_client = OpenAI(api_key=api_key, **client_kwargs)
            model_info = model_info_client.models.retrieve(model_name)
            if hasattr(model_info, "model_dump"):
                self._description = model_info.model_dump()
            elif hasattr(model_info, "dict"):
                self._description = model_info.dict()
            else:
                self._description = dict(model_info)
        except Exception:
            self._description = {"id": model_name, "object": "model"}

        self._settings_mapping = {
            "temperature": {"name": "temperature", "type": float, "section": [0.0, 2.0]},
            "max_tokens": {"name": "max_output_tokens", "type": int},
            "top_p": {"name": "top_p", "type": float, "section": [0.0, 1.0]},
            "stop": {"name": "stop", "type": list[str]},
            "tool_choice": {"name": "tool_choice", "type": (str, dict)},
        }

    def _encode_responses_content(self, content: object, role:str|None=None) -> list[dict]:
        encoded: list[dict] = []
        text_type="output_text" if role=="assistant" else "input_text"
        for block in content_blocks(content):
            if isinstance(block, str):
                encoded.append({"type": text_type, "text": block})
                continue
            if isinstance(block, TextMessageBlock):
                encoded.append({"type": text_type, "text": block.text})
                continue
            if isinstance(block, MediaMessageBlock):
                validate_media_capability(
                    provider="OpenAI",
                    model_name=self.model_name,
                    capabilities=self.capabilities,
                    block=block,
                )
                asset = block.asset
                if asset.modality == FieldModality.IMAGE:
                    if asset.source_kind == "file_id":
                        encoded.append({"type": "input_image", "file_id": str(asset.value)})
                    else:
                        image_url = str(asset.value) if asset.source_kind == "url" else asset_to_data_url(asset)
                        encoded.append({"type": "input_image", "image_url": image_url})
                    continue
                if asset.modality == FieldModality.PDF:
                    item = {"type": "input_file", "filename": asset.default_filename}
                    if asset.source_kind == "file_id":
                        item["file_id"] = str(asset.value)
                    elif asset.source_kind == "url":
                        item["file_url"] = str(asset.value)
                    else:
                        item["file_data"] = asset_to_base64(asset)
                    encoded.append(item)
                    continue
            encoded.append({"type": text_type, "text": str(block)})
        if not encoded:
            encoded.append({"type": text_type, "text": ""})
        return encoded

    def _encode_responses_input(self, messages: list[dict]) -> list[dict]:
        items: list[dict] = []
        for message in messages:
            role = message.get("role")
            if role == "tool":
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.get("tool_call_id"),
                        "output": content_to_text(message.get("content")),
                    }
                )
                continue

            tool_calls = canonical_tool_calls(message)
            if role == "assistant" and tool_calls:
                assistant_text = content_to_text(message.get("content"))
                if assistant_text:
                    items.append(
                        {
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": assistant_text}],
                        }
                    )
                for tool_call in tool_calls:
                    call_id = tool_call.get("id") or tool_call.get("call_id")
                    items.append(
                        {
                            "type": "function_call",
                            "call_id": call_id,
                            "id": call_id,
                            "name": tool_call.get("name"),
                            "arguments": json.dumps(tool_call.get("arguments", {}), ensure_ascii=False),
                        }
                    )
                continue

            items.append(
                {
                    "role": role,
                    "content": self._encode_responses_content(message.get("content"),role=role),
                }
            )
        return items

    def _parse_response(self, response) -> dict:
        result: dict = {}
        tool_calls: list[dict] = []
        assistant_content: list[TextMessageBlock] = []
        for item in getattr(response, "output", []) or []:
            item_type = getattr(item, "type", None)
            if item_type == "function_call":
                arguments = getattr(item, "arguments", "{}")
                try:
                    parsed_arguments = json.loads(arguments)
                except Exception:
                    parsed_arguments = {"input": arguments}
                tool_calls.append(
                    {
                        "id": getattr(item, "call_id", None) or getattr(item, "id", None),
                        "name": getattr(item, "name", None),
                        "arguments": parsed_arguments,
                    }
                )
                continue
            if item_type != "message":
                continue
            for block in getattr(item, "content", []) or []:
                block_type = getattr(block, "type", None)
                if block_type in {"output_text", "text"}:
                    text = getattr(block, "text", None)
                    if text:
                        assistant_content.append(TextMessageBlock(text=text))

        if tool_calls:
            result["type"] = ModelResponseType.TOOL_CALL
            result["content"] = tool_calls
            assistant_message_content: object = assistant_content if assistant_content else ""
            result["assistant_message"] = assistant_message_from_tool_calls(tool_calls, assistant_message_content)
        else:
            text = extract_openai_response_text(response)
            if not text:
                raise ValueError("Response is not valid")
            result["type"] = ModelResponseType.CONTENT
            result["content"] = text

        result["raw_response"] = response
        usage = getattr(response, "usage", None)
        if usage:
            input_usage = getattr(usage, "input_tokens", 0) or 0
            output_usage = getattr(usage, "output_tokens", 0) or 0
            self._token_tracker.accumulate(input_usage=input_usage, output_usage=output_usage)
        return result

    def invoke(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        settings: dict | None = None,
        **kwargs,
    ) -> dict:
        tools_dict = [{"type": "function", **tool} for tool in tools] if tools else None
        max_retries = kwargs.pop("max_retries", 3)
        base_delay = kwargs.pop("retry_base_delay", 1.0)

        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                response = self._client.responses.create(
                    model=self.model_name,
                    input=self._encode_responses_input(messages),
                    tools=tools_dict,
                    **self._parse_settings(settings),
                    **kwargs,
                )
                return self._parse_response(response)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                status_code = getattr(exc, "status_code", None)
                if status_code is None and hasattr(exc, "response"):
                    status_code = getattr(getattr(exc, "response", None), "status_code", None)
                retryable_status = {429, 500, 502, 503, 504}
                if status_code not in retryable_status and status_code is not None:
                    raise
                if attempt == max_retries - 1:
                    raise
                time.sleep(base_delay * (2 ** attempt))

        if last_exc:
            raise last_exc
        raise RuntimeError("OpenAIModel.invoke failed without specific exception")

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
        api_params = {"prompt": prompt, "n": n, "size": size}
        if model is not None:
            api_params["model"] = model
        if quality != "standard":
            api_params["quality"] = quality
        if response_format != "url":
            api_params["response_format"] = response_format
        if style != "vivid":
            api_params["style"] = style
        if user is not None:
            api_params["user"] = user
        api_params.update(kwargs)

        response = self._client.images.generate(**api_params)
        images: list[dict] = []
        for img_data in response.data:
            img_dict: dict = {}
            if hasattr(img_data, "url") and img_data.url:
                img_dict["url"] = img_data.url
            if hasattr(img_data, "b64_json") and img_data.b64_json:
                img_dict["b64_json"] = img_data.b64_json
            if hasattr(img_data, "revised_prompt") and img_data.revised_prompt:
                img_dict["revised_prompt"] = img_data.revised_prompt
            images.append(img_dict)
        return images
