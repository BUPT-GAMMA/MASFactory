from __future__ import annotations
from openai import OpenAI
from abc import ABC, abstractmethod
try:
    from anthropic import Anthropic  # type: ignore
except ImportError:  # pragma: no cover
    Anthropic = None  # type: ignore

try:
    from google import genai  # type: ignore
except ImportError:  # pragma: no cover
    genai = None  # type: ignore
from enum import Enum
import json
import time
from .token_usage_tracker import TokenUsageTracker

class ModelResponseType(Enum):
    """Canonical response variants returned by model adapters."""

    CONTENT = "content"
    TOOL_CALL = "tool_call"

class Model(ABC):
    """Base interface for model adapters.

    A `Model` wraps a provider client (OpenAI / Anthropic / Gemini) and exposes a unified
    `invoke()` API for chat-style requests with optional tool calling.
    """

    # NodeTemplate scoping: Model instances are typically shared service clients (HTTP connection pools, locks, etc.).
    # Mark them as shared to avoid accidental deepcopy and to keep NodeTemplate usage predictable.
    __node_template_scope__ = "shared"

    def __init__(self,model_name:str|None=None,invoke_settings:dict|None=None,*args,**kwargs):
        """Create a model adapter.

        Args:
            model_name: Provider model identifier.
            invoke_settings: Default settings merged into every invoke call (temperature, token limits, etc.).
            *args: Reserved for backward compatibility.
            **kwargs: Reserved for backward compatibility.
        """
        self._model_name = model_name
        self._description = None
        self._client = None
        self._default_invoke_settings = invoke_settings
        self._settings_mapping = {}
        self._settings_default = {
            "temperature": {
                "name": "temperature",
                "type":float,
                "section":[0.0,2.0]
            },
            "max_tokens": {
                "name": "max_tokens",
                "type":int,
            },
            "top_p": {
                "name": "top_p",
                "type":float,
                "section":[0.0,1.0]
            },
            "stop": {
                "name": "stop",
                "type": list[str],
            },
            "tool_choice": {
                "name": "tool_choice",
                "type": (str, dict),
            },
        }
        self._token_tracker = None 
    def _parse_settings(self, settings: dict | None) -> dict:
        """Parse and validate model invoke settings.

        - Merges `settings` with `self._default_invoke_settings`.
        - Drops keys with None values.
        - Validates types based on `self._settings_mapping`.
        - Coerces numeric types when safe.
        """
        from typing import get_args, get_origin

        if settings is None and self._default_invoke_settings is None:
            return {}
        if settings is None:
            settings = self._default_invoke_settings
        elif self._default_invoke_settings is not None:
            settings = {**self._default_invoke_settings, **settings}

        settings = {k: v for k, v in (settings or {}).items() if v is not None}

        def coerce_value(key: str, value: object, expected_type: object) -> object:
            origin = get_origin(expected_type)
            args = get_args(expected_type)

            if expected_type is float:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(
                        f"Invalid value type for {key}: {value} in {self._model_name}, which should be float"
                    )
                return float(value)

            if expected_type is int:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError(
                        f"Invalid value type for {key}: {value} in {self._model_name}, which should be int"
                    )
                return int(value)

            if origin is list:
                if not isinstance(value, list):
                    raise ValueError(
                        f"Invalid value type for {key}: {value} in {self._model_name}, which should be list"
                    )
                if args and args[0] is str and any(not isinstance(item, str) for item in value):
                    raise ValueError(
                        f"Invalid value type for {key}: {value} in {self._model_name}, which should be list[str]"
                    )
                return value

            if origin is dict:
                if not isinstance(value, dict):
                    raise ValueError(
                        f"Invalid value type for {key}: {value} in {self._model_name}, which should be dict"
                    )
                return value

            if isinstance(expected_type, tuple):
                if not isinstance(value, expected_type):
                    raise ValueError(
                        f"Invalid value type for {key}: {value} in {self._model_name}, which should be {expected_type}"
                    )
                return value

            if expected_type is None or expected_type is object:
                return value

            if not isinstance(value, expected_type):
                raise ValueError(
                    f"Invalid value type for {key}: {value} in {self._model_name}, which should be {expected_type}"
                )
            return value

        parsed: dict = {}
        for key, value in settings.items():
            if key not in self._settings_mapping:
                raise ValueError(f"Invalid model setting: {key} for {self._model_name}")
            mapping = self._settings_mapping[key]
            expected_type = mapping.get("type")
            value = coerce_value(key, value, expected_type)

            if isinstance(value, (int, float)) and not isinstance(value, bool):
                target_section = mapping.get("section")
                source_section = self._settings_default.get(key, {}).get("section")
                if target_section and source_section:
                    target_min_val, target_max_val = target_section
                    source_min_val, source_max_val = source_section
                    value = target_min_val + (value - source_min_val) * (target_max_val - target_min_val) / (
                        source_max_val - source_min_val
                    )

            parsed[mapping.get("name", key)] = value
        return parsed
    @property
    def model_name(self)->str:
        return self._model_name
    
    @property
    def description(self)->str:
        return self._description
    
    @property
    def token_tracker(self) -> TokenUsageTracker:
        return self._token_tracker

    @abstractmethod
    def invoke(self,
             messages:list[dict],
             tools:list[dict]|None,
             settings:dict|None=None,
             **kwargs) -> dict:
        """Invoke the model with chat messages and optional tool schemas.

        Args:
            messages: A list of chat messages, typically `{"role": ..., "content": ...}`.
            tools: Tool schemas for tool calling. Provider adapters may map these into the
                provider-specific tool format.
            settings: Model settings (temperature, max tokens, etc.). The adapter validates
                and maps settings to provider parameters.

        Returns:
            A dict with parsed response fields. Adapters commonly return:
            - `type`: `ModelResponseType.CONTENT` or `ModelResponseType.TOOL_CALL`
            - `content`: text content or tool call payloads
        """
        raise NotImplementedError("invoke method is not implemented")

    def generate_images(self,
                       prompt: str,
                       model: str = None,
                       n: int = 1,
                       quality: str = "standard",
                       response_format: str = "url",
                       size: str = "1024x1024",
                       style: str = "vivid",
                       user: str = None,
                       **kwargs) -> list[dict]:
        """Generate images for a text prompt.

        Providers that do not support image generation should raise NotImplementedError.
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not support image generation")

class OpenAIModel(Model):
    """OpenAI chat model adapter using the official OpenAI SDK."""

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str | None = None,
        invoke_settings: dict | None = None,
        **kwargs,
    ):
        """Create an OpenAI model adapter.

        Args:
            model_name: OpenAI model name.
            api_key: OpenAI API key.
            base_url: Optional custom API base URL (OpenAI-compatible).
            invoke_settings: Default settings merged into every invoke call.
            **kwargs: Forwarded to the OpenAI SDK client constructor.
        """
        super().__init__(model_name, invoke_settings, **kwargs)

        if api_key is None or api_key == "":
            raise ValueError("OpenAI api_key is required.")
        if model_name is None or model_name == "":
            raise ValueError("OpenAI model_name is required.")

        client_kwargs = dict(kwargs)
        if base_url:
            client_kwargs["base_url"] = base_url

        self._client = OpenAI(api_key=api_key, **client_kwargs)
        self._model_name = model_name
        self._token_tracker = TokenUsageTracker(
            model_name=model_name,
            api_key=api_key,
            base_url=base_url
        )
        try:
            model_info_client_kwargs = dict(client_kwargs)
            model_info_client = OpenAI(api_key=api_key, **model_info_client_kwargs)
            model_info = model_info_client.models.retrieve(model_name)
            # Try different methods to convert to dict
            if hasattr(model_info, 'model_dump'):
                self._description = model_info.model_dump()
            elif hasattr(model_info, 'dict'):
                self._description = model_info.dict()
            else:
                self._description = dict(model_info)
        except Exception as e:
            # If model retrieval fails, use a basic description
            self._description = {"id": model_name, "object": "model"}
        self._settings_mapping = {
            "temperature": {
                "name": "temperature",
                "type":float,
                "section":[0.0,2.0]
            },
            "max_tokens": {
                "name": "max_tokens",
                "type":int,
            },
            "top_p": {
                "name": "top_p",
                "type":float,
                "section":[0.0,1.0]
            },
            "stop": {
                "name": "stop",
                "type": list[str],
            },
            "tool_choice": {
                "name": "tool_choice",
                "type": (str, dict),
            },
            # "response_format": {
            #     "name": "response_format",
            #     "type": dict,
            # }
        }

    def _parse_response(self,response:OpenAI.ChatCompletion.create)->dict:
        result = {}
        if response.choices[0].message.tool_calls:
            result["type"] = ModelResponseType.TOOL_CALL
            result["content"] = []
            for tool_call in response.choices[0].message.tool_calls:
                result["content"].append({
                    "id": tool_call.id,
                    "name": tool_call.function.name,
                    "arguments": json.loads(tool_call.function.arguments)
                })
                result["raw_response"] = response
        elif response.choices[0].message.content:
            result["type"] = ModelResponseType.CONTENT
            result["content"] = response.choices[0].message.content
            result["raw_response"] = response
        else:
            raise ValueError("Response is not valid")
        
        if hasattr(response, 'usage') and response.usage:
            self._token_tracker.accumulate(
                input_usage=response.usage.prompt_tokens,
                output_usage=response.usage.completion_tokens
            )
        
        return result
    
    def invoke(self,
             messages:list[dict],
             tools:list[dict]|None,
             settings:dict|None=None,
             **kwargs)->dict:
        """Invoke the OpenAI chat completions API.

        Args:
            messages: Chat messages.
            tools: Tool schemas (converted into OpenAI function tools).
            settings: Per-call override settings merged with defaults.
            **kwargs: Additional OpenAI SDK parameters. Supports:
                - max_retries: retry count for transient errors
                - retry_base_delay: base delay for exponential backoff

        Returns:
            Parsed model response dict.
        """

        tools_dict = [{"type": "function", "function": tool} for tool in tools] if tools else None
        max_retries = kwargs.pop("max_retries", 3)
        base_delay = kwargs.pop("retry_base_delay", 1.0)

        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                response = self._client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    tools=tools_dict,
                    **self._parse_settings(settings),
                    **kwargs,
                )
                return self._parse_response(response)
            except Exception as e:  # noqa: BLE001
                last_exc = e

                status_code = getattr(e, "status_code", None)
                if status_code is None and hasattr(e, "response"):
                    status_code = getattr(getattr(e, "response", None), "status_code", None)

                retryable_status = {429, 500, 502, 503, 504}
                if status_code not in retryable_status and status_code is not None:
                    raise

                if attempt == max_retries - 1:
                    raise

                sleep_seconds = base_delay * (2 ** attempt)
                time.sleep(sleep_seconds)

        if last_exc:
            raise last_exc

        raise RuntimeError("OpenAIModel.invoke failed without specific exception")

    def generate_images(self,
                       prompt: str,
                       model: str = None,
                       n: int = 1,
                       quality: str = "standard",
                       response_format: str = "url",
                       size: str = "1024x1024",
                       style: str = "vivid",
                       user: str = None,
                       **kwargs) -> list[dict]:
        """Generate images using the OpenAI Images API.

        Args:
            prompt: Text prompt for the image generation request.
            model: Optional image model identifier.
            n: Number of images to generate.
            quality: Image quality setting.
            response_format: Output format (`url` or base64 JSON depending on provider support).
            size: Image size.
            style: Style preset when supported by the provider.
            user: Optional end-user identifier passed to the provider.
            **kwargs: Extra provider-specific parameters forwarded to the SDK call.

        Returns:
            A list of dicts with `url` and/or `b64_json` fields, depending on provider response.
        """
        api_params = {
            "prompt": prompt,
            "n": n,
            "size": size,
        }

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

        images = []
        for img_data in response.data:
            img_dict = {}

            if hasattr(img_data, 'url') and img_data.url:
                img_dict["url"] = img_data.url

            if hasattr(img_data, 'b64_json') and img_data.b64_json:
                img_dict["b64_json"] = img_data.b64_json

            if hasattr(img_data, 'revised_prompt') and img_data.revised_prompt:
                img_dict["revised_prompt"] = img_data.revised_prompt

            images.append(img_dict)

        return images

class AnthropicModel(Model):
    """Anthropic chat model adapter using the official Anthropic SDK."""

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str | None = None,
        invoke_settings: dict | None = None,
        **kwargs,
    ):
        """Create an Anthropic model adapter.

        Args:
            model_name: Anthropic model name.
            api_key: Anthropic API key.
            base_url: Optional custom API base URL.
            invoke_settings: Default settings merged into every invoke call.
            **kwargs: Forwarded to the Anthropic SDK client constructor.
        """
 
        super().__init__(model_name, invoke_settings, **kwargs)

        if model_name is None or model_name == "":
            raise ValueError("Anthropic model_name is required.")
        if api_key is None or api_key == "":
            raise ValueError("Anthropic api_key is required.")
        if Anthropic is None:
            raise ImportError(
                "Anthropic support requires the 'anthropic' package. "
                "Please install it with: pip install anthropic"
            )
        self._client = Anthropic(
            api_key=api_key,
            base_url=base_url,
            **kwargs,
            )
        self._model_name = model_name
        self._token_tracker = TokenUsageTracker(
            model_name=model_name,
            api_key=api_key,
            base_url=base_url
        )
        try:
            model_info = self._client.models.retrieve(model_name)
            if hasattr(model_info, "model_dump"):
                self._description = model_info.model_dump()
            elif hasattr(model_info, "dict"):
                self._description = model_info.dict()
            else:
                self._description = dict(model_info)
        except Exception:
            self._description = {"id": model_name, "object": "model"}
        self._settings_mapping = {
            "temperature": {
                "name": "temperature",
                "type":float,
                "section":[0.0,1.0]
            },
            "max_tokens": {
                "name": "max_tokens",
                "type":int,
            },
            "top_p": {
                "name": "top_p",
                "type":float,
                "section":[0.0,1.0]
            },
            "stop": {
                "name": "stop",
                "type": list[str],
            },
            "tool_choice": {
                "name": "tool_choice",
                "type": dict,
            },
        }
    def _parse_response(self, response) -> dict:
        result = {}
        if hasattr(response, 'content') and any(getattr(block, 'type', None) == 'tool_use' for block in response.content):
            result["type"] = ModelResponseType.TOOL_CALL
            tool_calls: list[dict] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                args = getattr(block, "input", None)
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {"input": args}
                tool_calls.append(
                    {
                        "id": getattr(block, "id", None),
                        "name": getattr(block, "name", None),
                        "arguments": args if args is not None else {},
                    }
                )
            result["content"] = tool_calls
        elif hasattr(response, 'content') and any(getattr(block, 'type', None) == 'text' for block in response.content):
            result["type"] = ModelResponseType.CONTENT
            text_content = ""
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    text_content += getattr(block, "text", "")
            result["content"] = text_content
        else:
            raise ValueError("Response is not valid or contains unsupported content")
        
        if hasattr(response, 'usage') and response.usage:
            self._token_tracker.accumulate(
                input_usage=response.usage.input_tokens,
                output_usage=response.usage.output_tokens
            )
        
        return result

    def invoke(self,
             messages:list[dict],
             tools:list[dict]|None,
             settings:dict|None=None,
             invoke_settings:dict|None=None,
             **kwargs) -> dict:
        """Invoke the Anthropic messages API.

        Args:
            messages: Chat messages (system/user/assistant/tool). System messages are passed via
                the Anthropic `system` parameter.
            tools: Tool schemas converted to Anthropic tool format.
            settings: Per-call override settings merged with defaults.
            invoke_settings: Reserved for backward compatibility.
            **kwargs: Additional Anthropic SDK parameters forwarded to `messages.create`.

        Returns:
            Parsed model response dict.
        """
        system_message = None
        anthropic_messages = []
        
        for message in messages:
            if message["role"] == "system":
                system_message = message["content"]
            else:
                anthropic_messages.append({
                    "role": message["role"],
                    "content": message["content"]
                })
        
        anthropic_tools = []
        if tools:
            for tool in tools:
                anthropic_tools.append({
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "input_schema": tool["parameters"]
                })

        response = self._client.messages.create(
            model=self.model_name,
            messages=anthropic_messages,
            system=system_message,
            tools=anthropic_tools if anthropic_tools else None,
            **self._parse_settings(settings),
            **kwargs
        )
    
        return self._parse_response(response)

    def generate_images(self,
                       prompt: str,
                       model: str = None,
                       n: int = 1,
                       quality: str = "standard",
                       response_format: str = "url",
                       size: str = "1024x1024",
                       style: str = "vivid",
                       user: str = None,
                       **kwargs) -> list[dict]:
        """Image generation is not supported for Anthropic models.

        Args:
            prompt: Text prompt for image generation.
            model: Optional image model identifier.
            n: Number of images to generate.
            quality: Image quality setting.
            response_format: Output format (`url` or base64 JSON depending on provider support).
            size: Image size.
            style: Style preset when supported by the provider.
            user: Optional end-user identifier passed to the provider.
            **kwargs: Extra provider-specific parameters.

        Raises:
            NotImplementedError: Always raised because Anthropic does not provide an Images API
                in the official SDK.
        """
        raise NotImplementedError(
            "Anthropic models do not support image generation. "
            "Please use OpenAI (DALL-E) or Google (Imagen) for image generation."
        )

class GeminiModel(Model):
    """Gemini chat model adapter using the `google-genai` SDK."""

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str | None = None,
        invoke_settings: dict | None = None,
        **kwargs,
    ):
        """Create a Gemini model adapter.

        Args:
            model_name: Gemini model name.
            api_key: Gemini API key.
            base_url: Optional custom API base URL.
            invoke_settings: Default settings merged into every invoke call.
            **kwargs: Forwarded to the Gemini client constructor.
        """
        super().__init__(model_name, invoke_settings, **kwargs)

        if model_name is None or model_name == "":
            raise ValueError("Gemini model_name is required.")
        if api_key is None or api_key == "":
            raise ValueError("Gemini api_key is required.")
        if genai is None:
            raise ImportError(
                "Gemini support requires the 'google-genai' package. "
                "Please install it with: pip install google-genai"
            )

        # Avoid passing duplicate keys if user provided them via kwargs.
        kwargs.pop("api_key", None)
        kwargs.pop("http_options", None)

        http_options = None
        if base_url:
            from google.genai import types

            http_options = types.HttpOptions(base_url=base_url)

        self._client = genai.Client(api_key=api_key, http_options=http_options, **kwargs)
        self._model_name = model_name
        self._token_tracker = TokenUsageTracker(
            model_name=model_name,
            api_key=api_key,
            base_url=base_url
        )
        try:
            model_info = self._client.models.get(model=model_name)
            if hasattr(model_info, "model_dump"):
                self._description = model_info.model_dump()
            elif hasattr(model_info, "dict"):
                self._description = model_info.dict()
            else:
                self._description = dict(model_info)
        except Exception:
            self._description = {"id": model_name, "object": "model"}
        self._settings_mapping = {
            "temperature": {
                "name": "temperature",
                "type":float,
                "section":[0.0,2.0],

            },
            "max_tokens": {
                "name": "max_output_tokens",
                "type":int,
            },
            "top_p": {
                "name": "top_p",
                "type":float,
                "section":[0.0,1.0]
            },
            "stop": {
                "name": "stop_sequences",
                "type": list[str],
            },
            "tool_choice": {
                "name": "tool_config",
                "type": dict,
            },
        }
    def _parse_response(self, response) -> dict:
        result: dict = {}

        tool_calls: list[dict] = []
        if hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                function_call = getattr(part, "function_call", None)
                if function_call:
                    tool_calls.append(
                        {
                            "id": getattr(function_call, "id", None),
                            "name": getattr(function_call, "name", None),
                            "arguments": getattr(function_call, "args", None) or {},
                        }
                    )

        if tool_calls:
            result["type"] = ModelResponseType.TOOL_CALL
            result["content"] = tool_calls
        elif hasattr(response, 'text') and response.text is not None:
            result["type"] = ModelResponseType.CONTENT
            result["content"] = response.text
        else:
            raise ValueError("Response is not valid or contains unsupported content")
        
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            self._token_tracker.accumulate(
                input_usage=response.usage_metadata.prompt_token_count,
                output_usage=response.usage_metadata.candidates_token_count
            )
        
        return result

    def invoke(self,
             messages:list[dict],
             tools:list[dict]|None,
             settings:dict|None=None,
             **kwargs) -> dict:
        """Invoke the Gemini generate_content API.

        Args:
            messages: Chat messages. System messages are mapped into `system_instruction`.
            tools: Tool schemas converted to Gemini function declarations.
            settings: Per-call override settings merged with defaults.
            **kwargs: Extra kwargs are ignored for compatibility (google-genai is strict).

        Returns:
            Parsed model response dict.
        """
        from google.genai import types

        if kwargs:
            # google-genai does not accept extra kwargs on generate_content; ignore for compatibility.
            print(f"[GeminiModel.invoke] Ignoring unexpected kwargs: {list(kwargs.keys())}")

        system_parts: list[str] = []
        contents: list[types.Content] = []

        for message in messages:
            role = message.get("role")
            content = message.get("content")

            if role == "system":
                if content is not None:
                    system_parts.append(str(content))
                continue

            if content is None:
                text = ""
            elif isinstance(content, str):
                text = content
            else:
                try:
                    text = json.dumps(content, ensure_ascii=False)
                except Exception:
                    text = str(content)

            if role == "assistant":
                role = "model"
            elif role == "tool":
                tool_name = message.get("name")
                if tool_name:
                    text = f"[tool:{tool_name}]\n{text}"
                role = "user"

            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=text)]))

        function_declarations: list[types.FunctionDeclaration] = []
        if tools:
            for tool in tools:
                function_declarations.append(
                    types.FunctionDeclaration(
                        name=tool.get("name"),
                        description=tool.get("description", ""),
                        parameters_json_schema=tool.get("parameters"),
                    )
                )

        config_kwargs = self._parse_settings(settings)
        if system_parts:
            config_kwargs["system_instruction"] = "\n\n".join(system_parts)
        if function_declarations:
            config_kwargs["tools"] = [types.Tool(function_declarations=function_declarations)]

        config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None
        response = self._client.models.generate_content(
            model=self.model_name,
            contents=contents,
            config=config,
        )

        return self._parse_response(response)

    def generate_images(self,
                       prompt: str,
                       model: str = None,
                       n: int = 1,
                       quality: str = "standard",
                       response_format: str = "url",
                       size: str = "1024x1024",
                       style: str = "vivid",
                       user: str = None,
                       **kwargs) -> list[dict]:
        """Generate images using Google Imagen via the Gemini SDK.

        Args:
            prompt: Text prompt for the image generation request.
            model: Optional Imagen model identifier.
            n: Number of images to generate.
            quality: Unused (kept for API symmetry).
            response_format: Unused (kept for API symmetry).
            size: Requested output size; mapped to Imagen size buckets.
            style: Unused (kept for API symmetry).
            user: Unused (kept for API symmetry).
            **kwargs: Extra parameters mapped to `GenerateImagesConfig` when supported.

        Returns:
            A list of dicts that include `b64_json` when image bytes are available.
        """
        size_mapping = {
            "256x256": "1K",
            "512x512": "1K",
            "1024x1024": "1K",
            "1792x1024": "2K",
            "1024x1792": "2K",
            "2048x2048": "2K",
        }
        imagen_size = size_mapping.get(size, "1K")

        imagen_model = model if model is not None else "imagen-3.0-generate-002"

        config = {
            "number_of_images": n,
            "image_size": imagen_size,
        }

        imagen_specific_params = [
            "aspect_ratio",
            "person_generation",
            "safety_filter_level",
            "negative_prompt",
            "language",
            "include_rai_reason",
            "output_mime_type",
            "compression_quality",
        ]

        for param in imagen_specific_params:
            if param in kwargs:
                config[param] = kwargs.pop(param)

        try:
            from google.genai import types

            # Map OpenAI-style arg name to google-genai field name.
            if "compression_quality" in config:
                config["output_compression_quality"] = config.pop("compression_quality")

            if kwargs:
                print(f"[GeminiModel.generate_images] Ignoring unexpected kwargs: {list(kwargs.keys())}")

            generation_config = types.GenerateImagesConfig(**config)
            response = self._client.models.generate_images(
                model=imagen_model,
                prompt=prompt,
                config=generation_config,
            )

            images = []
            for generated_image in response.generated_images:
                img_dict = {}

                if hasattr(generated_image, 'image') and hasattr(generated_image.image, 'image_bytes'):
                    import base64
                    img_dict["b64_json"] = base64.b64encode(generated_image.image.image_bytes).decode('utf-8')

                if hasattr(generated_image, 'image') and hasattr(generated_image.image, 'mime_type'):
                    img_dict["mime_type"] = generated_image.image.mime_type

                if hasattr(generated_image, 'rai_filtered_reason') and generated_image.rai_filtered_reason:
                    img_dict["rai_filtered_reason"] = generated_image.rai_filtered_reason

                images.append(img_dict)

            return images

        except ImportError:
            raise ImportError(
                "Google GenAI library is required for image generation. "
                "Please install it with: pip install google-genai"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to generate images with Gemini Imagen: {str(e)}")
