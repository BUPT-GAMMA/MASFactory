"""Context adapters for MASFactory.

This package defines the internal context pipeline used by Memory/Retrieval/MCP adapters.
It is intentionally adapter-oriented and does not introduce a new chat-message class; the
rest of the framework continues to use the existing list-of-dict message format.
"""

from .types import ContextBlock, ContextQuery
from .provider import ContextProvider
from .policy import ContextPolicy, DefaultContextPolicy
from .renderer import ContextRenderer, DefaultContextRenderer
from .composer import ContextComposer

__all__ = [
    "ContextBlock",
    "ContextQuery",
    "ContextProvider",
    "ContextPolicy",
    "DefaultContextPolicy",
    "ContextRenderer",
    "DefaultContextRenderer",
    "ContextComposer",
]
