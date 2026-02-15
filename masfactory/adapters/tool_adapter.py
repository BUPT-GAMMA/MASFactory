import inspect
import types
from typing import Any, List, Dict, Union, Callable, get_args, get_origin
from docstring_parser import parse

class ToolAdapter():
    """Adapter that exposes Python callables as LLM tool definitions."""

    def __init__(self, tools: list[Callable]):
        """Create a ToolAdapter.

        Args:
            tools: List of Python callables exposed as tools.
        """
        self._tools = tools
        self._tool_map = {tool.__name__: tool for tool in tools}
    def __str__(self) -> str:
        return f"ToolAdapter with tools: {self._tools}"
    
    def call(self, name: str, arguments: dict) -> str:
        return self._tool_map[name](**arguments)

    @property
    def tools(self) -> list[Callable]:
        return self._tools
    
    @property
    def details(self) -> list[dict]:
        """Return tool schemas in function-calling format."""
        def map_py_type_to_json(py_type: Any) -> Dict[str, Any]:
            origin = get_origin(py_type)

            # Handle both typing.Union[...] and PEP 604 unions (X | Y).
            if origin is Union or origin is types.UnionType:
                args = get_args(py_type)
                non_none_args = [arg for arg in args if arg is not type(None)]
                if len(non_none_args) == 1:
                    return map_py_type_to_json(non_none_args[0])
                return {"anyOf": [map_py_type_to_json(arg) for arg in args]}

            if py_type in (list, List):
                return {"type": "array"}

            if py_type in (dict, Dict):
                return {"type": "object"}

            if origin in (list, List):
                args = get_args(py_type)
                if args:
                    return {"type": "array", "items": map_py_type_to_json(args[0])}
                return {"type": "array"}

            if origin in (dict, Dict):
                return {"type": "object"}

            if py_type is str:
                return {"type": "string"}
            if py_type is int:
                return {"type": "integer"}
            if py_type is float:
                return {"type": "number"}
            if py_type is bool:
                return {"type": "boolean"}
            if py_type is type(None):
                return {"type": "null"}

            return {}

        def callable_to_json_schema(func: Callable) -> Dict[str, Any]:
            """Build JSON schema for one Python callable."""
            sig = inspect.signature(func)
            docstring = parse(func.__doc__ or "")
            param_docs = {p.arg_name: p.description for p in docstring.params}
            schema_properties = {}
            required_params = []
            for name, param in sig.parameters.items():
                if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                    continue
                if param.default is inspect.Parameter.empty:
                    required_params.append(name)
                py_type = param.annotation if param.annotation is not inspect.Parameter.empty else Any
                param_schema = map_py_type_to_json(py_type)
                if name in param_docs:
                    param_schema['description'] = param_docs[name]
                if param.default is not inspect.Parameter.empty:
                    param_schema['default'] = param.default
                schema_properties[name] = param_schema
            json_schema = {
                "type": "object",
                "properties": schema_properties,
            }
            
            if required_params:
                json_schema["required"] = required_params
                
            return json_schema

        description_dict:list[dict] = []
        for tool in self._tools:
            properties = callable_to_json_schema(tool)
            description_dict.append({
                "name": tool.__name__,
                "description": tool.__doc__,
                "parameters": properties
            })

        return description_dict
        
