from dataclasses import asdict, replace
from masfactory.core.node import Node
from masfactory.adapters.model import Model, ModelResponseType
from masfactory.utils.hook import masf_hook
from masfactory.adapters.tool_adapter import ToolAdapter
from masfactory.adapters.memory import Memory,HistoryMemory
from masfactory.adapters.retrieval import Retrieval
from typing import Any, Callable
import re
import json
from masfactory.core.message import MessageFormatter, StatefulFormatter
from masfactory.adapters.context import ContextComposer, ContextQuery, DefaultContextRenderer
from tenacity import retry,stop_after_attempt,wait_exponential
_UNSET = object()

# Some models might follow chain-of-thought style prompts and emit reasoning blocks.
# We strip these blocks before handing the content to output formatters to keep parsing robust.
_THINKING_BLOCK_PATTERN = re.compile(
    r"<\s*(think|thinking)\s*>.*?<\s*/\s*\1\s*>",
    flags=re.IGNORECASE | re.DOTALL,
)
def get_format_fields(content:str) -> set[str]:
    """Extract `{field}` placeholder names from a template string.

    This helper intentionally ignores escaped braces like `{{` / `}}`.

    Args:
        content: Template text.

    Returns:
        A set of placeholder field names found in the template.
    """
    pattern = re.compile(r'(?<!\{)\{([a-zA-Z_]\w*|\d+)\}(?!\})')
    field_names = pattern.findall(content)
    return set(field_names)
def str_format(content:str,format_dict:dict,*,value_renderer:Callable[[Any],str]) -> str:
    """Format a template string with `{field}` placeholders.

    This function behaves like a restricted `str.format`, with two differences:
    - Unknown placeholders are left unchanged instead of raising.
    - If a rendered value spans multiple lines, subsequent lines are indented to align with
      the placeholder column (with a minimum indent of 2 spaces).

    Args:
        content: Template text containing `{field}` placeholders.
        format_dict: Mapping used to fill placeholders.
        value_renderer: Renderer used for non-string values.
            Signature: `(value: Any) -> str`.

    Returns:
        The formatted string.
    """
    pattern = re.compile(r'(?<!\{)\{([a-zA-Z_]\w*|\d+)\}(?!\})')
    def replacer(match):
        field_name = match.group(1)
        value = format_dict.get(field_name, match.group(0))
        if isinstance(value, str):
            return value
        rendered = value_renderer(value)
        if "\n" not in rendered:
            return rendered
        line_start = content.rfind("\n", 0, match.start()) + 1
        column = match.start() - line_start
        prefix = " " * max(2, column)
        if column == 0:
            return "\n".join(f"{prefix}{line}" for line in rendered.splitlines())
        lines = rendered.splitlines()
        return lines[0] + "".join(f"\n{prefix}{line}" for line in lines[1:])
    formatted_content = pattern.sub(replacer, content)
    return formatted_content
def format_content_and_get_fields(content:str,format_dict:dict,uncontexted_knowledges_keys:set[str],*,value_renderer:Callable[[Any],str]) -> tuple[str,set[str]]:
    """Format a template string and track which fields were consumed.

    Args:
        content: Template text containing `{field}` placeholders.
        format_dict: Mapping used to fill placeholders.
        uncontexted_knowledges_keys: A set of keys that are available but not yet consumed by templating.
        value_renderer: Function that renders non-string values into strings.

    Returns:
        A tuple `(formatted_content, remaining_uncontexted_keys)`.
    """
    fields:set[str] = get_format_fields(content)
    uncontexted_knowledges_keys = uncontexted_knowledges_keys - fields
    unknown_fields = fields - format_dict.keys()
    if unknown_fields:
        raise KeyError(f"Unknown fields in content: {sorted(unknown_fields)}")
    formatted_content = str_format(content,format_dict,value_renderer=value_renderer)
    uncontexted_knowledges_keys = uncontexted_knowledges_keys - fields
    return formatted_content,uncontexted_knowledges_keys
class Agent(Node):
    """
    LLM-driven agent node.

    The agent builds prompts from instructions, input fields, memories, retrievers,
    and output-field constraints, then runs iterative think/act cycles with optional tools.
    """

    def __init__(self,
        name: str,
        instructions: str | list[str],
        *,
        model: Model,
        formatters: list[MessageFormatter] | MessageFormatter | None = None,
        max_retries: int | None = 3,
        retry_delay: int | None = 1,
        retry_backoff: int | None = 2,
        prompt_template: str | list[str] | None = None,
        tools: list[Callable] | None = None,
        memories: list[Memory] | None = None,
        retrievers: list[Retrieval] | None = None,
        pull_keys: dict[str, dict | str] | None | object = _UNSET,
        push_keys: dict[str, dict | str] | None | object = _UNSET,
        model_settings: dict | None = None,
        role_name: str | None = None,
        attributes: dict[str, object] | None = None,
        hide_unused_fields: bool = False,
    ):
        """Create an LLM-driven agent node.

        Args:
            name: Node name.
            instructions: System-level instructions for the agent.
            model: Model adapter used for invocation.
            formatters: Message formatter(s). If a single formatter is provided it is used for both
                input and output. If a list of two is provided, it is treated as `[in, out]`.
            max_retries: Max retries for model calls.
            retry_delay: Base delay multiplier for exponential backoff retries.
            retry_backoff: Exponential backoff base.
            prompt_template: Optional user prompt template (may contain `{field}` placeholders).
            tools: Optional tool callables available to the agent.
            memories: Optional memories attached to the agent.
            retrievers: Optional retrieval backends attached to the agent.
            pull_keys: Pull key policy for attributes. If omitted, defaults to `{}` for Agents.
            push_keys: Push key policy for attributes. If omitted, defaults to `{}` for Agents.
            model_settings: Provider/model settings passed into the adapter invoke call.
            role_name: Optional role label used in chat traces. Defaults to `name`.
            attributes: Optional default attributes local to this agent.
            hide_unused_fields: If True, omit unused fields when formatting prompts.
        """
        if pull_keys is _UNSET:
            pull_keys = {}
        elif pull_keys is not None:
            pull_keys = dict(pull_keys)

        if push_keys is _UNSET:
            push_keys = {}
        elif push_keys is not None:
            push_keys = dict(push_keys)

        attributes = {} if attributes is None else dict(attributes)

        Node.__init__(self, name=name, pull_keys=pull_keys, push_keys=push_keys, attributes=attributes)
        # For Agent, keep attributes isolated from pull_keys description placeholders.
        self._default_attributes = attributes.copy()
        self._attributes_store = self._default_attributes.copy()
        self._role_name:str = role_name if role_name is not None else name
        self._model = model
        if self._model is None:
            raise ValueError("Agent requires a non-None model instance.")
        if isinstance(instructions,list):
            instructions = '\n'.join(instructions)
        self._instructions:str = instructions
        self._prompt_template:str|None = prompt_template
        in_formatter = None
        out_formatter = None
        if formatters is None:
            from masfactory.core.message import JsonMessageFormatter, ParagraphMessageFormatter  # noqa: WPS433

            formatters = [ParagraphMessageFormatter(), JsonMessageFormatter()]

        if isinstance(formatters,MessageFormatter):
            in_formatter = formatters
            out_formatter = formatters
        elif isinstance(formatters,list) and len(formatters) == 1:
            in_formatter = formatters[0]
            out_formatter = formatters[0]
        elif isinstance(formatters,list) and len(formatters) == 2:
            in_formatter = formatters[0]
            out_formatter = formatters[1]
        else:
            raise ValueError("formatters must be a MessageFormatter or a list of two MessageFormatter")
        if in_formatter is None or not in_formatter.is_input_formatter:
            raise ValueError("in_formatter must be not None and an input formatter")
        if out_formatter is None or not out_formatter.is_output_formatter:
            raise ValueError("out_formatter must be not None and an output formatter")
        self._out_formatter:MessageFormatter = out_formatter
        self._in_formatter:MessageFormatter = in_formatter
        if memories is None:
            memories = []
        self._memories:list[Memory] = [memory for memory in memories if not isinstance(memory,HistoryMemory)]
        self._history_memories:list[HistoryMemory] = [memory for memory in memories if isinstance(memory,HistoryMemory)]
        # NOTE: `retrievers` may include MCP or other ContextProvider-like adapters.
        self._retrievers:list[Retrieval] = list(retrievers) if retrievers else []
        self._is_built:bool = True
        self._model_settings:dict = model_settings if model_settings else {}
        self._context_knowledges:dict = {}
        self._uncontexted_knowledges_keys:set[str] = set()
        max_retries = 3 if max_retries is None else int(max_retries)
        retry_delay = 1 if retry_delay is None else int(retry_delay)
        retry_backoff = 2 if retry_backoff is None else int(retry_backoff)

        self._max_retries = int(max_retries)
        self._retry_delay = int(retry_delay)
        self._retry_backoff = int(retry_backoff)
        self._user_tools: list[Callable] = list(tools) if tools else []
        self._tool_adapter: ToolAdapter | None = ToolAdapter(self._user_tools) if self._user_tools else None
        # Context tool-call support (active providers) is configured per invocation in observe().
        self._current_context_query: ContextQuery | None = None
        self._active_context_providers: list[object] = []
        self._active_context_provider_map: dict[str, object] = {}
        self._active_context_source_entries: list[dict] = []
        self._active_context_source_aliases: dict[str, list[str]] = {}
        self._context_tool_renderer = DefaultContextRenderer()
        self._hide_unused_fields:bool = hide_unused_fields
        self._last_user_message = ""
        self._last_system_message = ""
        self._memory_insert_counter = 0
    @property
    def last_prompt(self) -> tuple[str, str]:
        return self._last_system_message , self._last_user_message

    def __str__(self):
        return f"Agent {self.name} with input keys {self.input_keys} and output keys {self.output_keys}  and prompt {self.instructions}"

    def _output_keys_prompt(self) -> str:
        """Build formatter requirements and required output fields prompt payload."""
        formatter_context = self._out_formatter.agent_introducer
        required_fields = {**self.output_keys, **self._push_keys} if self._push_keys != None else self.output_keys
        description = {
            "RESPONSE FORMAT REQUIREMENTS": formatter_context,
            "REQUIRED OUTPUT FIELDS AND THEIR DESCRIPTIONS": json.dumps(required_fields, ensure_ascii=False, indent=2)
        }
        return description
    def _task_prompt(self,input:str) -> str:
        return f"""
        INPUT:
        {input}
        """

    def _task_description(self,input:dict) -> dict:
        description = {
            "TASK DESCRIPTION": input
        }
        return description

    def _prompt_template_format(self,prompt_template:str|list[str]|None) -> str|dict:
        """Render template placeholders with current context knowledge."""
        if isinstance(prompt_template,dict):
            formatted_instructions = prompt_template.copy()
            for key in formatted_instructions.keys():
                formatted_instructions[key],self._uncontexted_knowledges_keys = format_content_and_get_fields(
                    formatted_instructions[key],
                    self._context_knowledges,
                    self._uncontexted_knowledges_keys,
                    value_renderer=self._in_formatter.render_value,
                )
            return formatted_instructions
        elif isinstance(prompt_template,list):
            formatted_instructions = "\n".join(prompt_template)
            formatted_instructions,self._uncontexted_knowledges_keys = format_content_and_get_fields(
                formatted_instructions,
                self._context_knowledges,
                self._uncontexted_knowledges_keys,
                value_renderer=self._in_formatter.render_value,
            )
            return formatted_instructions
        elif isinstance(prompt_template,str) and  prompt_template != "":
            formatted_instructions,self._uncontexted_knowledges_keys = format_content_and_get_fields(
                prompt_template,
                self._context_knowledges,
                self._uncontexted_knowledges_keys,
                value_renderer=self._in_formatter.render_value,
            )
            return formatted_instructions
        else:
            return ""
    def _system_prompt(self) -> dict|str:
        formatted_instructions = self._prompt_template_format(self._instructions)
        return formatted_instructions
        
    def _input_prompt(self) -> dict:
        formatted_input = self._prompt_template_format(self._prompt_template)
        return {
            "MESSAGE TO YOU":formatted_input
        }

    @property
    def history_messages(self) -> list:
        """Return deduplicated chat history messages from history memories."""
        if len(self._history_memories) == 0:
            return []
        messages = []
        for memory in self._history_memories:
            memory_messages = memory.get_messages(top_k=0)
            for memory_message in memory_messages:
                messages.append({"role": memory_message["role"], "content": memory_message["content"]})
        unique_messages = []
        for message in messages:
            if message not in unique_messages:
                unique_messages.append(message)
        messages = unique_messages
        return messages

    def _context_fileds_prompt(self) -> dict:
        """Build additional context fields not consumed during template formatting."""
        if self._context_knowledges is None or len(self._context_knowledges) == 0:
            return {}
        addition_context = {}
        for key in self._uncontexted_knowledges_keys:
            addition_context[key] = self._context_knowledges[key]
        return addition_context

    def _user_prompt(self) -> dict:
        """Build complete user prompt payload."""
        input_prompt = self._input_prompt()
        if not self._hide_unused_fields:
            context_fileds_prompt = self._context_fileds_prompt()
        else:
            context_fileds_prompt = {}
        output_keys_prompt = self._output_keys_prompt()
        user_prompt = {**input_prompt,**context_fileds_prompt,**output_keys_prompt}
        return user_prompt
    @masf_hook(Node.Hook.BUILD)
    def build(self):
        self._is_built = True

    def _update_context_knowledges(self,input_dict:dict[str,object]):
        """Refresh context knowledge from attributes, input, and role placeholders."""
        if self._attributes_store is not None and len(self._attributes_store) > 0:
            self._context_knowledges.update(self._attributes_store)
        self._context_knowledges.update(input_dict)
        self._context_knowledges.update({"role_name": self._role_name})
        # Agent intentionally keeps _attributes_store isolated from pull_keys description placeholders.
        # To avoid hard failures during prompt formatting, inject missing pull_keys as placeholders.
        if isinstance(self._pull_keys, dict) and len(self._pull_keys) > 0:
            for key, desc in self._pull_keys.items():
                if key not in self._context_knowledges:
                    self._context_knowledges[key] = desc
        self._uncontexted_knowledges_keys = set(self._context_knowledges.keys())

    def _configure_stateful_formatters(self) -> None:
        """
        If the configured formatter is stateful, inject the current output field keys.
        """
        out_formatter = getattr(self, "_out_formatter", None)
        if not isinstance(out_formatter, StatefulFormatter):
            return
        field_keys: dict[str, object] = {}
        if isinstance(self._push_keys, dict):
            field_keys.update(self._push_keys)
        field_keys.update(self.output_keys)
        out_formatter.set_field_keys(field_keys)

    @masf_hook(Node.Hook.FORWARD)
    def _forward(self, input:dict[str,object]) -> dict:
        return self.step(input)

    def observe(self, input_dict: dict[str, object]) -> tuple[str, str, list[dict]]:
        """Prepare prompts and conversation messages for one model round."""
        self._update_context_knowledges(input_dict)
        self._configure_stateful_formatters()

        system_prompt = self._in_formatter.dump(self._system_prompt())
        user_payload = self._user_prompt()

        query_text = self._build_context_query_text(input_dict, user_payload)
        base_query = ContextQuery(
            query_text=query_text,
            inputs=self._context_knowledges,
            attributes=self._attributes_store,
            node_name=self.name,
        )

        def _is_passive_provider(provider: object) -> bool:
            if not getattr(provider, "supports_passive", True):
                return False
            return bool(getattr(provider, "passive", True))

        def _is_active_provider(provider: object) -> bool:
            if not getattr(provider, "supports_active", True):
                return False
            return bool(getattr(provider, "active", False))

        all_providers = [*self._memories, *self._retrievers]
        passive_providers = [p for p in all_providers if _is_passive_provider(p)]
        active_providers = [p for p in all_providers if _is_active_provider(p)]

        composer = ContextComposer(providers=passive_providers, history_providers=[*self._history_memories])
        history_messages = composer.get_history_messages(base_query, top_k=-1)
        query = ContextQuery(
            query_text=query_text,
            inputs=self._context_knowledges,
            attributes=self._attributes_store,
            node_name=self.name,
            messages=history_messages,
        )
        user_payload = composer.inject_user_payload(user_payload, query)
        # Expose active providers for tool-call retrieval.
        self._current_context_query = query
        self._active_context_providers = active_providers
        # Disambiguate provider labels for tool-call sources.
        base_labels: list[str] = []
        for provider in active_providers:
            label = getattr(provider, "context_label", provider.__class__.__name__)
            if not isinstance(label, str) or not label.strip():
                label = provider.__class__.__name__
            base_labels.append(label)

        from collections import Counter, defaultdict  # noqa: WPS433

        counts = Counter(base_labels)
        seq: defaultdict[str, int] = defaultdict(int)
        source_entries: list[tuple[str, str, object]] = []
        for provider, base_label in zip(active_providers, base_labels):
            if counts[base_label] == 1:
                source_name = base_label
            else:
                seq[base_label] += 1
                source_name = f"{base_label}#{seq[base_label]}"
            source_entries.append((source_name, base_label, provider))

        self._active_context_provider_map = {name: provider for name, _label, provider in source_entries}
        self._active_context_source_aliases = {
            base_label: [name for name, label, _p in source_entries if label == base_label]
            for base_label, cnt in counts.items()
            if cnt > 1
        }
        self._active_context_source_entries = [
            {"name": name, "label": base_label, "type": provider.__class__.__name__}
            for name, base_label, provider in source_entries
        ]

        tools: list[Callable] = list(self._user_tools)
        if active_providers:
            existing_names = {t.__name__ for t in tools}

            list_tool_name = "list_context_sources"
            retrieve_tool_name = "retrieve_context"
            if list_tool_name in existing_names:
                list_tool_name = "masfactory_list_context_sources"
            if retrieve_tool_name in existing_names:
                retrieve_tool_name = "masfactory_retrieve_context"

            def list_context_sources() -> dict:
                """List available active context sources for tool-call retrieval.

                Returns:
                    A dict shaped like:
                    `{\"sources\": [{\"name\": str, \"type\": str}]}`.
                """
                return {"sources": list(self._active_context_source_entries)}

            list_context_sources.__name__ = list_tool_name

            def retrieve_context(source: str, query: str, top_k: int = 8) -> dict:
                """Retrieve context blocks from a named active source.

                Args:
                    source: Name from `list_context_sources()` (provider label).
                    query: Search query text.
                    top_k: Max number of blocks to return (0 means "as many as possible").

                Returns:
                    A dict with:
                    - `provider`: provider label
                    - `query`: effective query text
                    - `blocks`: list of structured blocks
                    - `rendered`: blocks rendered as text for prompting
                """
                provider = self._active_context_provider_map.get(source)
                if provider is None:
                    aliases = self._active_context_source_aliases.get(source)
                    if aliases:
                        raise ValueError(
                            f"Ambiguous context source: {source}. "
                            f"Choose one of: {aliases} (call list_context_sources first)."
                        )
                    raise ValueError(
                        f"Unknown context source: {source}. "
                        f"Available: {sorted(self._active_context_provider_map.keys())}"
                    )
                base = self._current_context_query or ContextQuery(query_text=query or "")
                effective = replace(base, query_text=(query or base.query_text))
                blocks = provider.get_blocks(effective, top_k=int(top_k))  # type: ignore[attr-defined]

                rendered = ""
                injected = self._context_tool_renderer.inject({}, [(source, blocks)]) if blocks else {}
                if injected and "CONTEXT" in injected:
                    rendered = str(injected["CONTEXT"])

                return {
                    "provider": source,
                    "query": effective.query_text,
                    "blocks": [asdict(b) for b in blocks],
                    "rendered": rendered,
                }

            retrieve_context.__name__ = retrieve_tool_name

            tools.extend([list_context_sources, retrieve_context])

        self._tool_adapter = ToolAdapter(tools) if tools else None

        user_prompt = self._in_formatter.dump(user_payload)

        messages = [
            {"role": "system", "content": system_prompt},
            *history_messages,
            {"role": "user", "content": user_prompt},
        ]
        return system_prompt, user_prompt, messages

    def _build_context_query_text(self, input_dict: dict[str, object], user_payload: dict) -> str:
        """Best-effort query text used by retrieval-style providers."""
        for key in ("input", "task", "task_description", "question", "query", "message", "content", "text"):
            value = input_dict.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        if "MESSAGE TO YOU" in user_payload:
            value = user_payload.get("MESSAGE TO YOU")
            if isinstance(value, str) and value.strip():
                return value.strip()
        if len(input_dict) == 1:
            only_value = next(iter(input_dict.values()))
            if isinstance(only_value, str) and only_value.strip():
                return only_value.strip()
        try:
            return json.dumps(input_dict, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            return str(input_dict)

    def think(self, messages: list[dict], *, settings: dict | None = None) -> dict:
        """Invoke the underlying model adapter for one reasoning step.

        Args:
            messages: Chat messages passed to the model adapter. Items are commonly shaped like
                `{\"role\": ..., \"content\": ...}`.
            settings: Optional per-call model settings merged with this Agent's defaults.

        Returns:
            Provider-normalized response dict produced by `Model.invoke()`. At minimum this
            includes a `type` field (see `ModelResponseType`). When `type` is TOOL_CALL,
            `content` contains tool call items.
        """
        return self._model.invoke(
            messages=messages,
            tools=self._tool_adapter.details if self._tool_adapter else None,
            settings=settings,
        )

    def act(self, tool_calls: list[dict]) -> list[dict]:
        """Execute tool calls and return tool-result messages."""
        if not self._tool_adapter:
            raise ValueError("Tool call requested but no tools are configured on this Agent.")

        tool_results: list[dict] = []
        for tool_call in tool_calls:
            tool_call_result = self._tool_adapter.call(tool_call["name"], tool_call["arguments"])
            tool_results.append(
                {
                    "role": "tool",
                    "content": self._in_formatter.render_value(tool_call_result),
                    "tool_call_id": tool_call.get("id"),
                }
            )
        return tool_results

    def _strip_thinking_blocks(self, content: object) -> object:
        """Remove <think>...</think> / <thinking>...</thinking> blocks from model text outputs."""
        if not isinstance(content, str):
            return content
        stripped = _THINKING_BLOCK_PATTERN.sub("", content)
        return stripped.strip()

    def step(self, input_dict: dict[str, object]) -> dict:
        """Run one full observe/think/act loop and return formatted output."""

        # NOTE: We keep the retry semantics of the original forward implementation:
        # retry covers both model IO and output-format validation errors.
        @retry(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=self._retry_delay, exp_base=self._retry_backoff),
        )
        def _run_once() -> tuple[dict, str, str, str]:
            system_prompt, user_prompt, messages = self.observe(input_dict)

            max_tool_calls = 10
            tool_call_count = 0

            while True:
                # Keep per-call settings isolated so we can safely tweak tool_choice.
                settings = self._model_settings.copy() if self._model_settings else None
                if settings and tool_call_count >= 1 and settings.get("tool_choice") == "required":
                    settings["tool_choice"] = "auto"

                response: dict = self.think(messages, settings=settings)
                if response["type"] == ModelResponseType.CONTENT:
                    response_content = self._strip_thinking_blocks(response["content"])
                    response_content_dict = self._out_formatter.format(response_content)
                    for key in self.output_keys:
                        if key not in response_content_dict:
                            raise ValueError(f"Response content does not contain key: {key}")
                    return response_content_dict, response_content, system_prompt, user_prompt

                if response["type"] != ModelResponseType.TOOL_CALL:
                    raise ValueError("Response is not valid")

                tool_call_count += 1
                if tool_call_count > max_tool_calls:
                    raise ValueError(
                        f"Exceeded maximum tool calls ({max_tool_calls}). Possible infinite loop."
                    )

                tool_calls = response["content"]
                tool_results = self.act(tool_calls)

                # Preserve existing behavior: append the raw assistant tool-call message
                # when available (OpenAI), then append tool results.
                raw_response = response.get("raw_response")
                assistant_message = None
                if raw_response is not None:
                    choices = getattr(raw_response, "choices", None)
                    if choices:
                        assistant_message = getattr(choices[0], "message", None)
                if assistant_message is not None:
                    messages.append(assistant_message)
                messages.extend(tool_results)

        response_content_dict, response_content, system_prompt, user_prompt = _run_once()

        self._last_user_message = user_prompt
        self._last_system_message = system_prompt

        for memory in self._memories:
            self._memory_insert_counter += 1
            try:
                memory_key = json.dumps(
                    {"role_name": self._role_name, "turn": self._memory_insert_counter, "input": input_dict},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
            except Exception:
                memory_key = str(
                    {"role_name": self._role_name, "turn": self._memory_insert_counter, "input": input_dict}
                )
            memory.insert(memory_key, response_content)

        for memory in self._history_memories:
            memory.insert("user", user_prompt)
            memory.insert("assistant", response_content)

        return response_content_dict

    @property
    def model(self) -> Model:
        return self._model

    @property
    def instructions(self) -> str:
        return self._instructions

    @property
    def tools(self) -> list[Callable]:
        return self._tool_adapter.tools if self._tool_adapter else []

    def add_memory(self, memory: Memory):
        self._memories.append(memory)
        
    def add_retriever(self, retriever: Retrieval):
        self._retrievers.append(retriever)
    
    def reset_memories(self):
        """Reset all memory adapters."""
        if self._memories is not None:
            for memory in self._memories:
                memory.reset()
        if self._history_memories is not None:
            for memory in self._history_memories:
                memory.reset()

    def reset(self):
        self.reset_memories()
        super().reset()
